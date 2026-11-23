/**
 * Delivery Reports & Analytics Module Controller (Phase 9.6)
 * Handles campaign delivery performance inspection, real-time message KPIs,
 * batch status audits, and failed recipient tracking.
 */

(function () {
  'use strict';

  const state = {
    campaigns: [],
    selectedCampaignId: null,
    reportData: null,
    failedRecipients: [],
    isLoading: false,
    initialized: false,
  };

  function escapeHtml(text) {
    if (text === null || text === undefined) return '';
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function formatDateTime(isoString) {
    if (!isoString) return 'None';
    try {
      let s = String(isoString).trim();
      if (!s.endsWith('Z') && !/[+-]\d{2}:\d{2}$/.test(s)) {
        s = s.replace(' ', 'T') + 'Z';
      }
      const d = new Date(s);
      if (isNaN(d.getTime())) return String(isoString);
      const formatter = new Intl.DateTimeFormat('en-IN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
        timeZoneName: 'short',
      });
      const parts = formatter.formatToParts(d);
      const m = {};
      for (const p of parts) {
        m[p.type] = p.value;
      }
      const tz = m.timeZoneName || 'IST';
      return `${m.year}-${m.month}-${m.day} ${m.hour}:${m.minute}:${m.second} ${tz}`;
    } catch {
      return String(isoString);
    }
  }

  function showToast(message, type = 'success') {
    const toast = document.getElementById('toastNotification');
    const msgEl = document.getElementById('toastMessage');
    const iconEl = document.getElementById('toastIcon');
    if (!toast || !msgEl) return;

    toast.className = `toast ${type}`;
    msgEl.textContent = message;
    if (iconEl) {
      iconEl.textContent = type === 'success' ? '✓' : '⚠';
    }
    toast.classList.remove('hidden');

    setTimeout(() => {
      toast.classList.add('hidden');
    }, 3500);
  }

  // =========================================================================
  // 1. Load Campaigns Selector
  // =========================================================================

  async function loadCampaigns() {
    const select = document.getElementById('reportsCampaignSelect');
    if (!select) return;

    try {
      const res = await API.get('/api/campaigns');
      if (!res || !res.ok) {
        throw new Error('Failed to load campaigns list');
      }

      const resData = await res.json();
      state.campaigns = Array.isArray(resData) ? resData : (resData?.campaigns || resData?.items || []);

      if (state.campaigns.length === 0) {
        select.innerHTML = '<option value="">No campaigns found</option>';
        renderEmptyState('No campaigns available. Create a campaign first to view delivery analytics.');
        return;
      }

      select.innerHTML = '<option value="">-- Select a Campaign to Analyze --</option>' +
        state.campaigns.map(c => `
          <option value="${c.id}" ${state.selectedCampaignId === c.id ? 'selected' : ''}>
            #${c.id} — ${escapeHtml(c.campaign_name || c.name || 'Campaign #' + c.id)} (${c.status})
          </option>
        `).join('');

      // Auto-select first active or latest campaign if none selected
      if (!state.selectedCampaignId && state.campaigns.length > 0) {
        const activeOne = state.campaigns.find(c => c.status === 'Active' || c.status === 'Completed' || c.status === 'In Progress') || state.campaigns[0];
        select.value = activeOne.id;
        state.selectedCampaignId = activeOne.id;
        await loadCampaignReport(activeOne.id);
      }
    } catch (err) {
      console.error('Error loading campaigns for reports:', err);
      select.innerHTML = `<option value="">Error loading campaigns</option>`;
    }
  }

  // =========================================================================
  // 2. Load Campaign Report & Failed Recipients
  // =========================================================================

  async function loadCampaignReport(campaignId) {
    if (!campaignId) return;
    state.selectedCampaignId = campaignId;

    const reportContent = document.getElementById('reportsContentSection');
    const emptyState = document.getElementById('reportsEmptyState');
    const loadingState = document.getElementById('reportsLoadingState');
    const refreshBtn = document.getElementById('reportsRefreshBtn');

    try {
      state.isLoading = true;
      if (refreshBtn) refreshBtn.classList.add('loading');
      if (loadingState) loadingState.classList.remove('hidden');
      if (reportContent) reportContent.classList.add('hidden');
      if (emptyState) emptyState.classList.add('hidden');

      // Fetch report & failed recipients in parallel
      const [reportRes, failedRes] = await Promise.all([
        API.get(`/api/campaigns/${campaignId}/report`),
        API.get(`/api/campaigns/${campaignId}/failed-recipients`),
      ]);

      if (!reportRes || !reportRes.ok) {
        throw new Error('Failed to load campaign delivery report');
      }

      state.reportData = await reportRes.json();
      const failedRaw = failedRes && failedRes.ok ? await failedRes.json() : [];
      state.failedRecipients = Array.isArray(failedRaw) ? failedRaw : (failedRaw.failed_recipients || failedRaw.items || []);

      renderReport(state.reportData, state.failedRecipients);

      if (loadingState) loadingState.classList.add('hidden');
      if (reportContent) reportContent.classList.remove('hidden');
    } catch (err) {
      console.error('Error fetching campaign report:', err);
      if (loadingState) loadingState.classList.add('hidden');
      showToast(err.message || 'Error loading report', 'error');
    } finally {
      state.isLoading = false;
      if (refreshBtn) refreshBtn.classList.remove('loading');
    }
  }

  function renderReport(report, failedRecipients) {
    // Header summary
    const nameEl = document.getElementById('reportCampaignName');
    const statusEl = document.getElementById('reportCampaignStatus');
    if (nameEl) nameEl.textContent = report.name || report.campaign_name || 'Campaign #' + report.campaign_id;
    if (statusEl) {
      statusEl.textContent = report.status;
      statusEl.className = `badge badge-${(report.status || '').toLowerCase()}`;
    }

    // Delivery Metrics Cards
    const totalEl = document.getElementById('reportTotalRecipients');
    const sentEl = document.getElementById('reportSentCount');
    const deliveredEl = document.getElementById('reportDeliveredCount');
    const readEl = document.getElementById('reportReadCount');
    const failedEl = document.getElementById('reportFailedCount');
    const rateEl = document.getElementById('reportDeliveryRate');
    const progressBar = document.getElementById('reportDeliveryProgressBar');

    const totalPartitioned = report.total_partitioned_recipients !== undefined ? report.total_partitioned_recipients : (report.total_recipients || 0);
    const sent = report.sent_count !== undefined ? report.sent_count : (report.sent_messages || 0);
    const delivered = report.delivered_count !== undefined ? report.delivered_count : (report.delivered_messages || 0);
    const read = report.read_count !== undefined ? report.read_count : (report.read_messages || 0);
    const failed = report.failed_count !== undefined ? report.failed_count : (report.failed_messages || 0);

    if (totalEl) totalEl.textContent = totalPartitioned.toLocaleString();
    if (sentEl) sentEl.textContent = sent.toLocaleString();
    if (deliveredEl) deliveredEl.textContent = delivered.toLocaleString();
    if (readEl) readEl.textContent = read.toLocaleString();
    if (failedEl) failedEl.textContent = failed.toLocaleString();

    // Delivery Rate Calculation (0% when no messages sent/delivered, never false 100%)
    const deliveryRate = typeof report.delivery_rate === 'number'
      ? report.delivery_rate
      : (sent > 0 ? Math.round((delivered / sent) * 100) : 0);
    if (rateEl) rateEl.textContent = `${deliveryRate}%`;
    if (progressBar) {
      progressBar.style.width = `${Math.min(100, deliveryRate)}%`;
      progressBar.style.backgroundColor = deliveryRate >= 80 ? 'var(--success)' : (deliveryRate >= 50 ? 'var(--warning)' : 'var(--danger)');
    }

    // Batch Breakdown
    const bTotalEl = document.getElementById('reportBatchesTotal');
    const bPendingEl = document.getElementById('reportBatchesPending');
    const bApprovedEl = document.getElementById('reportBatchesApproved');
    const bSentEl = document.getElementById('reportBatchesSent');
    const bRejectedEl = document.getElementById('reportBatchesRejected');

    if (bTotalEl) bTotalEl.textContent = report.batches_total || 0;
    if (bPendingEl) bPendingEl.textContent = report.batches_pending || 0;
    if (bApprovedEl) bApprovedEl.textContent = report.batches_approved || 0;
    if (bSentEl) bSentEl.textContent = report.batches_sent || 0;
    if (bRejectedEl) bRejectedEl.textContent = report.batches_rejected || 0;

    // Failed Recipients Audit Table
    const failedTbody = document.getElementById('reportFailedTableBody');
    const failedEmpty = document.getElementById('reportFailedEmpty');
    const failedTableContainer = document.getElementById('reportFailedTableContainer');

    if (!failedRecipients || failedRecipients.length === 0) {
      if (failedEmpty) failedEmpty.classList.remove('hidden');
      if (failedTableContainer) failedTableContainer.classList.add('hidden');
    } else {
      if (failedEmpty) failedEmpty.classList.add('hidden');
      if (failedTableContainer) failedTableContainer.classList.remove('hidden');
      if (failedTbody) {
        failedTbody.innerHTML = failedRecipients.map((f, idx) => `
          <tr>
            <td>${idx + 1}</td>
            <td><span class="badge badge-active">Batch #${f.batch_number || f.batch_id || '—'}</span></td>
            <td><strong>${escapeHtml(f.customer_name || f.lead_name || ('Lead #' + (f.lead_id || '—')))}</strong></td>
            <td><code>${escapeHtml(f.phone_number || '—')}</code></td>
            <td><span style="color: var(--danger); font-size: 0.8rem; font-weight: 500;">${escapeHtml(f.error_message || f.error_details || 'Dispatch failure')}</span></td>
            <td><small class="text-muted">${formatDateTime(f.attempted_at || f.failed_at || f.created_at)}</small></td>
          </tr>
        `).join('');
      }
    }
  }

  function renderEmptyState(message) {
    const reportContent = document.getElementById('reportsContentSection');
    const emptyState = document.getElementById('reportsEmptyState');
    const emptyDesc = document.getElementById('reportsEmptyDesc');
    const nameEl = document.getElementById('reportCampaignName');
    const statusEl = document.getElementById('reportCampaignStatus');

    if (reportContent) reportContent.classList.add('hidden');
    if (emptyState) emptyState.classList.remove('hidden');
    if (emptyDesc) emptyDesc.textContent = message;
    if (nameEl) nameEl.textContent = 'No Campaign Selected';
    if (statusEl) {
      statusEl.textContent = '--';
      statusEl.className = 'badge';
    }
  }

  // =========================================================================
  // 3. Module Initialization
  // =========================================================================

  function init() {
    if (state.initialized) {
      if (state.selectedCampaignId) {
        loadCampaignReport(state.selectedCampaignId);
      } else {
        loadCampaigns();
      }
      return;
    }

    const select = document.getElementById('reportsCampaignSelect');
    if (select) {
      select.addEventListener('change', (e) => {
        const val = e.target.value ? parseInt(e.target.value, 10) : null;
        if (val) {
          loadCampaignReport(val);
        } else {
          renderEmptyState('Select a campaign to inspect its delivery metrics.');
        }
      });
    }

    const refreshBtn = document.getElementById('reportsRefreshBtn');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => {
        if (state.selectedCampaignId) {
          loadCampaignReport(state.selectedCampaignId);
        } else {
          loadCampaigns();
        }
      });
    }

    state.initialized = true;
    loadCampaigns();
  }

  window.ReportsManager = {
    init,
    loadCampaigns,
    loadCampaignReport,
  };
})();
