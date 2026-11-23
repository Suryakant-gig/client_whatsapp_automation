/**
 * Batch Approvals Module Controller (Phase 9.5)
 * Dedicated human approval interface for recipient batches across all campaigns.
 * Enforces mandatory individual review, recipient inspection, and safe message dispatching.
 */

(function () {
  const state = {
    page: 1,
    pageSize: 20,
    statusFilter: 'Pending', // Default view shows batches awaiting review
    items: [],
    total: 0,
    totalPages: 1,
    initialized: false,
    activeBatch: null,
  };

  // Helper: XSS escaping
  function escapeHtml(text) {
    if (text === null || text === undefined) return '';
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // Helper: Format datetime in local timezone (IST)
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

  // Helper: Toast notification
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

  // Approval badge helper
  function getApprovalBadge(status) {
    const s = escapeHtml(status || 'Pending');
    if (status === 'Pending' || status === 'PENDING_APPROVAL') {
      return `<span class="badge badge-pending">PENDING_APPROVAL</span>`;
    }
    if (status === 'Approved' || status === 'APPROVED') {
      return `<span class="badge badge-approved">Approved</span>`;
    }
    if (status === 'Rejected' || status === 'REJECTED') {
      return `<span class="badge badge-rejected">Rejected</span>`;
    }
    return `<span class="badge">${s}</span>`;
  }

  // Send status badge helper
  function getSendBadge(status) {
    const s = escapeHtml(status || 'Pending');
    switch (status) {
      case 'Pending':
        return `<span class="badge badge-pending">Pending</span>`;
      case 'In Progress':
        return `<span class="badge badge-in-progress">In Progress</span>`;
      case 'Completed':
        return `<span class="badge badge-completed">Completed</span>`;
      case 'Partially Failed':
        return `<span class="badge badge-partially-failed">Partially Failed</span>`;
      case 'Failed':
        return `<span class="badge badge-failed">Failed</span>`;
      default:
        return `<span class="badge">${s}</span>`;
    }
  }

  // 1. Fetch batches across campaigns
  async function loadBatches() {
    const tbody = document.getElementById('approvalsTableBody');
    const loadingState = document.getElementById('approvalsLoadingState');
    const emptyState = document.getElementById('approvalsEmptyState');
    const errorState = document.getElementById('approvalsErrorState');
    const paginationBar = document.getElementById('approvalsPaginationBar');

    if (loadingState) loadingState.classList.remove('hidden');
    if (emptyState) emptyState.classList.add('hidden');
    if (errorState) errorState.classList.add('hidden');
    if (tbody) tbody.innerHTML = '';

    try {
      const params = new URLSearchParams();
      params.set('page', state.page);
      params.set('page_size', state.pageSize);
      if (state.statusFilter) params.set('approval_status', state.statusFilter);

      const res = await API.get(`/api/campaigns/batches/all?${params.toString()}`);
      if (!res || !res.ok) {
        throw new Error(`Failed to load batches (HTTP ${res ? res.status : 'ERR'})`);
      }

      const data = await res.json();
      state.items = data.items || [];
      state.total = data.total || 0;
      state.totalPages = data.pages || 1;

      if (loadingState) loadingState.classList.add('hidden');

      if (state.items.length === 0) {
        if (emptyState) emptyState.classList.remove('hidden');
        if (paginationBar) paginationBar.classList.add('hidden');
        return;
      }

      if (paginationBar) paginationBar.classList.remove('hidden');
      renderApprovalsTable(state.items);
      renderPagination();
    } catch (err) {
      console.error('Error loading approvals:', err);
      if (loadingState) loadingState.classList.add('hidden');
      if (errorState) {
        errorState.classList.remove('hidden');
        const errDesc = document.getElementById('approvalsErrorText');
        if (errDesc) errDesc.textContent = err.message || 'Network error fetching approval batches.';
      }
    }
  }

  // 2. Render approvals table
  function renderApprovalsTable(items) {
    const tbody = document.getElementById('approvalsTableBody');
    if (!tbody) return;

    tbody.innerHTML = items.map(b => {
      const isPending = b.approval_status === 'Pending' || b.approval_status === 'PENDING_APPROVAL';
      const isApproved = b.approval_status === 'Approved' || b.approval_status === 'APPROVED';
      const canSend = isApproved && b.send_status === 'Pending';

      return `
        <tr>
          <td>
            <strong style="color: var(--primary);">Batch #${b.batch_number}</strong>
            ${b.scheduled_at ? `<div style="font-size: 0.72rem; color: #6366f1; margin-top: 0.2rem; white-space: nowrap;" title="Scheduled carry-forward dispatch">${formatDateTime(b.scheduled_at)}</div>` : ''}
          </td>
          <td>
            <strong>${escapeHtml(b.campaign_name)}</strong>
            <div style="font-size: 0.75rem; color: var(--text-muted);">${escapeHtml(b.template_name || '')}</div>
          </td>
          <td>
            <span class="badge" style="background: #f1f5f9; color: #334155; font-weight: 600;">
              ${b.batch_size} Recipients
            </span>
          </td>
          <td>${getApprovalBadge(b.approval_status)}</td>
          <td>${getSendBadge(b.send_status)}</td>
          <td>
            <small>
              <strong style="color: var(--success);">${b.sent_messages_count}</strong> sent /
              <strong style="color: var(--danger);">${b.failed_messages_count}</strong> failed
            </small>
          </td>
          <td><small class="text-muted">${formatDateTime(b.created_at)}</small></td>
          <td class="text-right">
            <div class="row-actions-group">
              <button class="btn-table-action" data-action="review" data-campaign-id="${b.campaign_id}" data-batch-id="${b.id}" title="Inspect Recipients">
                Recipients
              </button>
              ${isPending ? `
                <button class="btn-table-action btn-action-success" data-action="approve" data-campaign-id="${b.campaign_id}" data-batch-id="${b.id}" title="Approve batch">
                  Approve
                </button>
                <button class="btn-table-action btn-action-danger" data-action="reject" data-campaign-id="${b.campaign_id}" data-batch-id="${b.id}" title="Reject batch">
                  Reject
                </button>
              ` : ''}
              ${canSend ? `
                <button class="btn-table-action btn-action-primary" data-action="send" data-campaign-id="${b.campaign_id}" data-batch-id="${b.id}" title="Dispatch WhatsApp Messages">
                  Send
                </button>
              ` : ''}
            </div>
          </td>
        </tr>
      `;
    }).join('');

    // Attach row action listeners
    tbody.querySelectorAll('button[data-action]').forEach(btn => {
      btn.addEventListener('click', () => {
        const action = btn.getAttribute('data-action');
        const cId = parseInt(btn.getAttribute('data-campaign-id'), 10);
        const bId = parseInt(btn.getAttribute('data-batch-id'), 10);

        if (action === 'review') {
          openBatchReview(cId, bId);
        } else if (action === 'approve') {
          handleApproveBatch(cId, bId);
        } else if (action === 'reject') {
          handleRejectBatch(cId, bId);
        } else if (action === 'send') {
          handleSendBatch(cId, bId);
        }
      });
    });
  }

  // 3. Render pagination
  function renderPagination() {
    const rangeText = document.getElementById('approvalsRangeText');
    const totalCount = document.getElementById('approvalsTotalCount');
    const badge = document.getElementById('approvalsCurrentPageBadge');
    const prevBtn = document.getElementById('approvalsPrevBtn');
    const nextBtn = document.getElementById('approvalsNextBtn');

    if (totalCount) totalCount.textContent = state.total.toLocaleString();

    const start = state.total === 0 ? 0 : (state.page - 1) * state.pageSize + 1;
    const end = Math.min(state.page * state.pageSize, state.total);
    if (rangeText) rangeText.textContent = `${start}-${end}`;

    if (badge) badge.textContent = `Page ${state.page} of ${Math.max(1, state.totalPages)}`;
    if (prevBtn) prevBtn.disabled = state.page <= 1;
    if (nextBtn) nextBtn.disabled = state.page >= state.totalPages;
  }

  // 4. Open Batch Review / Recipients Modal
  async function openBatchReview(campaignId, batchId) {
    const modal = document.getElementById('batchReviewModal');
    const titleNum = document.getElementById('batchReviewNumber');
    const titleCamp = document.getElementById('batchReviewCampaignName');
    const appBadge = document.getElementById('batchReviewApprovalBadge');
    const sendBadge = document.getElementById('batchReviewSendBadge');
    const sizeBadge = document.getElementById('batchReviewSizeBadge');
    const tbody = document.getElementById('batchRecipientsTableBody');

    const approveBtn = document.getElementById('batchReviewApproveBtn');
    const rejectBtn = document.getElementById('batchReviewRejectBtn');
    const sendBtn = document.getElementById('batchReviewSendBtn');

    if (modal) modal.classList.remove('hidden');
    if (tbody) tbody.innerHTML = '<tr><td colspan="7" class="text-center p-3">Loading recipient records...</td></tr>';

    try {
      const res = await API.get(`/api/campaigns/${campaignId}/batches/${batchId}`);
      if (!res.ok) throw new Error('Failed to fetch batch recipients');

      const batch = await res.json();
      state.activeBatch = batch;

      if (titleNum) titleNum.textContent = batch.batch_number;
      if (titleCamp) titleCamp.textContent = `Campaign #${batch.campaign_id}`;
      if (appBadge) appBadge.innerHTML = getApprovalBadge(batch.approval_status);
      if (sendBadge) sendBadge.innerHTML = getSendBadge(batch.send_status);
      if (sizeBadge) sizeBadge.textContent = `${batch.batch_size} Recipients`;

      // Configure footer action buttons
      const isPending = batch.approval_status === 'Pending' || batch.approval_status === 'PENDING_APPROVAL';
      const isApproved = batch.approval_status === 'Approved' || batch.approval_status === 'APPROVED';

      if (approveBtn) {
        approveBtn.style.display = isPending ? 'inline-flex' : 'none';
        approveBtn.onclick = () => handleApproveBatch(campaignId, batchId, true);
      }
      if (rejectBtn) {
        rejectBtn.style.display = isPending ? 'inline-flex' : 'none';
        rejectBtn.onclick = () => handleRejectBatch(campaignId, batchId, true);
      }
      if (sendBtn) {
        sendBtn.style.display = (isApproved && batch.send_status === 'Pending') ? 'inline-flex' : 'none';
        sendBtn.onclick = () => handleSendBatch(campaignId, batchId, true);
      }

      const recipients = batch.recipients || [];
      if (recipients.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center p-4 text-muted">No recipients recorded in this batch.</td></tr>';
        return;
      }

      tbody.innerHTML = recipients.map((r, idx) => `
        <tr>
          <td><span class="table-id-badge">${idx + 1}</span></td>
          <td><strong>${escapeHtml(r.customer_name || 'Unknown')}</strong></td>
          <td><code>${escapeHtml(r.phone_number || '--')}</code></td>
          <td>${getSendBadge(r.send_status)}</td>
          <td>${r.message_log_id ? `<span class="badge" style="background: #e0e7ff; color: #3730a3;">Msg #${r.message_log_id}</span>` : '<span class="text-muted">--</span>'}</td>
          <td><small class="text-muted">${formatDateTime(r.sent_at)}</small></td>
          <td>${r.error_details ? `<span style="color: var(--danger); font-size: 0.75rem;">${escapeHtml(r.error_details)}</span>` : '<span class="text-muted">None</span>'}</td>
        </tr>
      `).join('');
    } catch (err) {
      showToast(err.message || 'Error loading batch recipients', 'error');
    }
  }

  // 5. Approve Batch
  async function handleApproveBatch(campaignId, batchId, fromModal = false) {
    if (!confirm(`Mandatory Review: Grant administrator approval for Batch #${batchId}? Messages will not be sent automatically.`)) return;

    try {
      const res = await API.post(`/api/campaigns/${campaignId}/batches/${batchId}/approve`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Approval failed');
      }
      showToast(`Batch #${batchId} has been approved!`, 'success');
      loadBatches();
      if (fromModal) {
        openBatchReview(campaignId, batchId);
      }
      if (window.CampaignsManager) {
        window.CampaignsManager.loadCampaigns();
      }
    } catch (err) {
      showToast(err.message || 'Approval error', 'error');
    }
  }

  // 6. Reject Batch
  async function handleRejectBatch(campaignId, batchId, fromModal = false) {
    if (!confirm(`Are you sure you want to REJECT Batch #${batchId}? Rejected batches cannot be dispatched.`)) return;

    try {
      const res = await API.post(`/api/campaigns/${campaignId}/batches/${batchId}/reject`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Rejection failed');
      }
      showToast(`Batch #${batchId} has been rejected.`, 'success');
      loadBatches();
      if (fromModal) {
        openBatchReview(campaignId, batchId);
      }
      if (window.CampaignsManager) {
        window.CampaignsManager.loadCampaigns();
      }
    } catch (err) {
      showToast(err.message || 'Rejection error', 'error');
    }
  }

  // 7. Send Batch
  async function handleSendBatch(campaignId, batchId, fromModal = false) {
    if (!confirm(`Initiate WhatsApp dispatch for Batch #${batchId}? Consent and eligibility will be revalidated immediately before sending.`)) return;

    try {
      const res = await API.post(`/api/campaigns/${campaignId}/batches/${batchId}/send`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Dispatch failed');
      }
      const data = await res.json();
      showToast(`Batch dispatch completed: ${data.sent_count} sent, ${data.failed_count} failed, ${data.skipped_count} skipped.`, 'success');
      loadBatches();
      if (fromModal) {
        openBatchReview(campaignId, batchId);
      }
      if (window.CampaignsManager) {
        window.CampaignsManager.loadCampaigns();
      }
    } catch (err) {
      showToast(err.message || 'Dispatch error', 'error');
    }
  }

  // 8. Init controller
  function init() {
    if (state.initialized) {
      loadBatches();
      return;
    }
    state.initialized = true;

    // Refresh button
    const refreshBtn = document.getElementById('refreshApprovalsBtn');
    if (refreshBtn) refreshBtn.addEventListener('click', loadBatches);

    // Status filter tabs
    document.querySelectorAll('.approvals-tab-btn').forEach(tab => {
      tab.addEventListener('click', () => {
        document.querySelectorAll('.approvals-tab-btn').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        state.statusFilter = tab.getAttribute('data-status') || '';
        state.page = 1;
        loadBatches();
      });
    });

    // Pagination
    const prevBtn = document.getElementById('approvalsPrevBtn');
    if (prevBtn) {
      prevBtn.addEventListener('click', () => {
        if (state.page > 1) {
          state.page--;
          loadBatches();
        }
      });
    }

    const nextBtn = document.getElementById('approvalsNextBtn');
    if (nextBtn) {
      nextBtn.addEventListener('click', () => {
        if (state.page < state.totalPages) {
          state.page++;
          loadBatches();
        }
      });
    }

    const pageSizeSelect = document.getElementById('approvalsPageSizeSelect');
    if (pageSizeSelect) {
      pageSizeSelect.addEventListener('change', () => {
        state.pageSize = parseInt(pageSizeSelect.value, 10);
        state.page = 1;
        loadBatches();
      });
    }

    // Modal Close
    const closeReviewBtn = document.getElementById('closeBatchReviewBtn');
    const closeReviewHeaderBtn = document.getElementById('closeBatchReviewHeaderBtn');
    const reviewModal = document.getElementById('batchReviewModal');
    [closeReviewBtn, closeReviewHeaderBtn].forEach(b => {
      if (b) b.addEventListener('click', () => reviewModal.classList.add('hidden'));
    });

    loadBatches();
  }

  // Export to window
  window.ApprovalsManager = {
    init,
    loadBatches,
    openBatchReview,
  };
})();
