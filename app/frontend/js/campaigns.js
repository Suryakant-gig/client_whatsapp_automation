/**
 * Campaign Management Module Controller (Phase 9.5)
 * Handles campaign listing, creation with approved WhatsApp templates,
 * candidate recipient eligibility preview, campaign editing, batch inspection,
 * and dispatch triggers.
 */

(function () {
  const state = {
    page: 1,
    pageSize: 20,
    statusFilter: '',
    search: '',
    items: [],
    total: 0,
    totalPages: 1,
    initialized: false,
    activeCampaign: null,
    templates: [],
    eligibleLeads: [],
    selectedLeadIds: new Set(),
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

  // Campaign & Template Presentation Display Mappings (Professional Travel Agency Names)
  const CAMPAIGN_DISPLAY_MAP = {
    'qwertyui': 'Goa Beachfront Weekend Special',
    'goa_rephse': 'Goa Monsoon Re-engagement Campaign',
    'Rejection Test Camp 060948': 'Rajasthan Heritage Tour Inquiries',
    'E2E Holiday Broadcast 060948 (Updated)': 'Diwali Holiday Broadcast (Early Bird)',
    'E2E Holiday Broadcast 060948': 'Diwali Holiday Broadcast',
  };

  const TEMPLATE_DISPLAY_MAP = {
    'phase95_verified_template': 'Goa Monsoon Getaway',
    'live_test_tmpl': 'Winter Maldives Promo',
    'quick_reply_welcome': 'Kerala Backwaters Early Bird',
  };

  function getCampaignDisplayName(name) {
    if (!name) return 'Untitled Campaign';
    return CAMPAIGN_DISPLAY_MAP[name] || name;
  }

  function getTemplateDisplayName(name) {
    if (!name) return 'Standard Broadcast';
    if (TEMPLATE_DISPLAY_MAP[name]) return TEMPLATE_DISPLAY_MAP[name];
    return name.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
  }

  // Campaign status badge
  function getCampaignStatusBadge(status) {
    const s = escapeHtml(status || 'Draft');
    switch (status) {
      case 'Draft':
        return `<span class="badge badge-draft">Draft</span>`;
      case 'Scheduled':
        return `<span class="badge badge-scheduled">Scheduled</span>`;
      case 'In Progress':
        return `<span class="badge badge-in-progress">In Progress</span>`;
      case 'Completed':
        return `<span class="badge badge-completed">Completed</span>`;
      case 'Cancelled':
        return `<span class="badge badge-failed">Cancelled</span>`;
      default:
        return `<span class="badge">${s}</span>`;
    }
  }

  // Batch approval badge
  function getBatchApprovalBadge(status) {
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

  // Batch send badge
  function getBatchSendBadge(status) {
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

  // 1. Load campaigns list
  async function loadCampaigns() {
    const tbody = document.getElementById('campaignsTableBody');
    const loadingState = document.getElementById('campaignsLoadingState');
    const emptyState = document.getElementById('campaignsEmptyState');
    const errorState = document.getElementById('campaignsErrorState');
    const paginationBar = document.getElementById('campaignsPaginationBar');

    if (loadingState) loadingState.classList.remove('hidden');
    if (emptyState) emptyState.classList.add('hidden');
    if (errorState) errorState.classList.add('hidden');
    if (tbody) tbody.innerHTML = '';

    try {
      const params = new URLSearchParams();
      params.set('page', state.page);
      params.set('page_size', state.pageSize);
      if (state.statusFilter) params.set('status', state.statusFilter);

      const res = await API.get(`/api/campaigns?${params.toString()}`);
      if (!res || !res.ok) {
        throw new Error(`Failed to load campaigns (HTTP ${res ? res.status : 'ERR'})`);
      }

      const data = await res.json();
      state.items = data.items || [];
      state.total = data.total || 0;
      state.totalPages = data.pages || 1;

      // Filter in-memory if search query exists
      let displayItems = state.items;
      if (state.search.trim()) {
        const query = state.search.toLowerCase().trim();
        displayItems = displayItems.filter(c => {
          const cName = (c.campaign_name || '').toLowerCase();
          const dispCName = getCampaignDisplayName(c.campaign_name).toLowerCase();
          const tName = (c.template_name || '').toLowerCase();
          const dispTName = getTemplateDisplayName(c.template_name).toLowerCase();
          return cName.includes(query) || dispCName.includes(query) || tName.includes(query) || dispTName.includes(query);
        });
      }

      if (loadingState) loadingState.classList.add('hidden');

      if (displayItems.length === 0) {
        if (emptyState) emptyState.classList.remove('hidden');
        if (paginationBar) paginationBar.classList.add('hidden');
        return;
      }

      if (paginationBar) paginationBar.classList.remove('hidden');
      renderCampaignsTable(displayItems);
      renderPagination();
    } catch (err) {
      console.error('Error loading campaigns:', err);
      if (loadingState) loadingState.classList.add('hidden');
      if (errorState) {
        errorState.classList.remove('hidden');
        const errDesc = document.getElementById('campaignsErrorText');
        if (errDesc) errDesc.textContent = err.message || 'Network error fetching campaigns.';
      }
    }
  }

  // 2. Render campaigns table rows
  function renderCampaignsTable(items) {
    const tbody = document.getElementById('campaignsTableBody');
    if (!tbody) return;

    tbody.innerHTML = items.map(c => {
      const canEdit = c.status === 'Draft' || c.status === 'Scheduled';
      const displayName = getCampaignDisplayName(c.campaign_name);
      const tplDisplayName = getTemplateDisplayName(c.template_name);
      return `
        <tr>
          <td><span class="table-id-badge">#${c.id}</span></td>
          <td>
            <strong>${escapeHtml(displayName)}</strong>
            ${c.campaign_name !== displayName ? `<small class="text-muted" style="display: block; font-size: 0.75rem;">${escapeHtml(c.campaign_name)}</small>` : ''}
          </td>
          <td>
            ${getCampaignStatusBadge(c.status)}
            ${c.scheduled_at ? `<small style="color: var(--primary); display: block; margin-top: 0.25rem;">${formatDateTime(c.scheduled_at)}</small>` : ''}
          </td>
          <td>
            <div style="font-weight: 500;">${escapeHtml(tplDisplayName)}</div>
            <small class="text-muted">${escapeHtml(c.template_name || 'None')} &bull; Lang: ${escapeHtml(c.template_language || 'en')}</small>
          </td>
          <td>
            <span title="Selected: ${c.total_leads_selected}, Excluded: ${c.total_leads_excluded}">
              <strong style="color: var(--success);">${c.total_leads_eligible}</strong>
              <small class="text-muted">/ ${c.total_leads_selected} leads</small>
            </span>
          </td>
          <td>
            <span class="badge" style="background: #f1f5f9; color: #334155; font-weight: 600;">
              ${c.batch_count} ${c.batch_count === 1 ? 'Batch' : 'Batches'}
            </span>
          </td>
          <td><small class="text-muted">${formatDateTime(c.created_at)}</small></td>
          <td class="text-right">
            <div class="row-actions-group">
              <button class="btn-table-action" data-action="details" data-id="${c.id}" title="View Details & Batches">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>
                Details
              </button>
              ${canEdit ? `
                <button class="btn-table-action" data-action="edit" data-id="${c.id}" title="Edit Campaign">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
                  Edit
                </button>
              ` : ''}
              ${c.status === 'Draft' || c.batch_count === 0 ? `
                <button class="btn-table-action btn-action-accent" data-action="generate" data-id="${c.id}" title="Partition Eligible Leads into Batches">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect></svg>
                  Partition
                </button>
              ` : ''}
            </div>
          </td>
        </tr>
      `;
    }).join('');

    // Attach row action listeners
    tbody.querySelectorAll('button[data-action]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const action = btn.getAttribute('data-action');
        const id = parseInt(btn.getAttribute('data-id'), 10);
        if (action === 'details') openCampaignDetail(id);
        else if (action === 'edit') openCampaignEdit(id);
        else if (action === 'generate') handleGenerateBatches(id);
      });
    });
  }

  // 3. Render pagination controls
  function renderPagination() {
    const rangeText = document.getElementById('campaignsRangeText');
    const totalCount = document.getElementById('campaignsTotalCount');
    const badge = document.getElementById('campaignsCurrentPageBadge');
    const prevBtn = document.getElementById('campaignsPrevBtn');
    const nextBtn = document.getElementById('campaignsNextBtn');

    if (totalCount) totalCount.textContent = state.total.toLocaleString();

    const start = state.total === 0 ? 0 : (state.page - 1) * state.pageSize + 1;
    const end = Math.min(state.page * state.pageSize, state.total);
    if (rangeText) rangeText.textContent = `${start}-${end}`;

    if (badge) badge.textContent = `Page ${state.page} of ${Math.max(1, state.totalPages)}`;
    if (prevBtn) prevBtn.disabled = state.page <= 1;
    if (nextBtn) nextBtn.disabled = state.page >= state.totalPages;
  }

  // Render Template Preview Box (Task 4.3)
  function renderTemplatePreview(templateName) {
    const previewBox = document.getElementById('createTemplatePreviewBox');
    const langInput = document.getElementById('createTemplateLanguage');
    const catBadge = document.getElementById('previewTemplateCategory');
    const langBadge = document.getElementById('previewTemplateLang');
    const headerSec = document.getElementById('previewHeaderSection');
    const headerTextEl = document.getElementById('previewHeaderText');
    const bodyEl = document.getElementById('templatePreviewBody');
    const varsEl = document.getElementById('templatePreviewVars');

    if (!previewBox) return;

    if (!templateName) {
      previewBox.classList.add('hidden');
      return;
    }

    const tpl = (state.templates || []).find(t => t.template_name === templateName);
    if (!tpl) {
      previewBox.classList.add('hidden');
      return;
    }

    if (langInput) langInput.value = tpl.language || 'en';
    if (catBadge) catBadge.textContent = tpl.category || 'MARKETING';
    if (langBadge) langBadge.textContent = `Language: ${tpl.language || 'en'}`;

    if (tpl.header_text && headerSec && headerTextEl) {
      headerTextEl.textContent = tpl.header_text;
      headerSec.classList.remove('hidden');
    } else if (tpl.header_type === 'IMAGE' && tpl.header_image_url && headerSec && headerTextEl) {
      headerTextEl.innerHTML = `<img src="${escapeHtml(tpl.header_image_url)}" style="max-height: 140px; border-radius: 4px; display: block; margin-top: 0.25rem;">`;
      headerSec.classList.remove('hidden');
    } else if (headerSec) {
      headerSec.classList.add('hidden');
    }

    if (bodyEl) {
      let bodyFormatted = escapeHtml(tpl.body_text || 'No message body preview provided.');
      // Highlight variables {{1}} or {{var_name}}
      bodyFormatted = bodyFormatted.replace(/\{\{([^}]+)\}\}/g, '<span class="template-var-pill">{{$1}}</span>');
      bodyEl.innerHTML = bodyFormatted;
    }

    if (varsEl) {
      const params = tpl.expected_parameters || [];
      if (params.length > 0) {
        varsEl.innerHTML = `<strong>Required Parameters:</strong> ${params.map(p => `<span class="template-var-pill">${escapeHtml(p)}</span>`).join(' ')}`;
      } else {
        varsEl.innerHTML = `<em>No dynamic variables required for this template.</em>`;
      }
    }

    previewBox.classList.remove('hidden');
  }

  // Render Specific Leads Checklist (Task 4.1)
  function renderSpecificLeadsList(query = '') {
    const listEl = document.getElementById('specificLeadsList');
    const countEl = document.getElementById('specificLeadsSelectedCount');
    const totalEl = document.getElementById('specificLeadsTotalAvailable');
    if (!listEl) return;

    let leads = state.eligibleLeads || [];
    if (totalEl) totalEl.textContent = `Available: ${leads.length}`;

    if (query.trim()) {
      const q = query.toLowerCase().trim();
      leads = leads.filter(l =>
        (l.customer_name && l.customer_name.toLowerCase().includes(q)) ||
        (l.phone_number && l.phone_number.includes(q)) ||
        (l.destination && l.destination.toLowerCase().includes(q))
      );
    }

    if (leads.length === 0) {
      listEl.innerHTML = '<div style="padding: 1rem; text-align: center; color: var(--text-muted); font-size: 0.8rem;">No matching eligible leads found.</div>';
    } else {
      listEl.innerHTML = leads.map(l => {
        const isChecked = state.selectedLeadIds.has(l.id);
        return `
          <label class="specific-lead-row">
            <div class="specific-lead-info">
              <input type="checkbox" class="lead-select-checkbox" value="${l.id}" ${isChecked ? 'checked' : ''}>
              <strong>${escapeHtml(l.customer_name || 'Unnamed')}</strong>
              <code>${escapeHtml(l.phone_number || '')}</code>
              ${l.destination ? `<small class="text-muted">(${escapeHtml(l.destination)})</small>` : ''}
            </div>
            <span class="specific-lead-badge">${escapeHtml(l.opt_in_status || 'OPTED_IN')}</span>
          </label>
        `;
      }).join('');
    }

    if (countEl) countEl.textContent = state.selectedLeadIds.size.toLocaleString();
    updateLiveBatchPlanPreview();
  }

  // Update Dynamic Batch Partition & Carry-Forward Plan Preview
  function updateLiveBatchPlanPreview() {
    const textEl = document.getElementById('batchPlanPreviewText');
    if (!textEl) return;

    const isSpecific = document.getElementById('targetModeSpecific')?.checked;
    let candidateCount = isSpecific
      ? state.selectedLeadIds.size
      : (state.eligibleCount || state.eligibleLeads?.length || 0);

    const maxInput = document.getElementById('createMaxRecipients');
    const maxVal = maxInput && maxInput.value ? parseInt(maxInput.value, 10) : null;
    if (maxVal && maxVal > 0 && maxVal < candidateCount) {
      candidateCount = maxVal;
    }

    const batchSizeInput = document.getElementById('createBatchSize');
    const batchSize = Math.max(1, Math.min(50, parseInt(batchSizeInput?.value, 10) || 50));

    const intervalSelect = document.getElementById('createCarryForwardInterval');
    const intervalHours = parseInt(intervalSelect?.value, 10) || 0;

    if (candidateCount === 0) {
      textEl.textContent = '0 candidate contacts selected — No batches will be generated.';
      return;
    }

    const batchCount = Math.ceil(candidateCount / batchSize);
    const sizes = [];
    let remaining = candidateCount;
    for (let i = 0; i < batchCount; i++) {
      const s = Math.min(remaining, batchSize);
      sizes.push(s);
      remaining -= s;
    }

    const sizesStr = sizes.join(', ');
    const batchWord = batchCount === 1 ? 'batch' : 'batches';

    if (intervalHours === 0) {
      textEl.innerHTML = `<strong>${candidateCount} contacts</strong> selected &rarr; <strong>${batchCount} ${batchWord}</strong> (${sizesStr}), partitioned and dispatched at once upon batch approval.`;
    } else {
      const intervalText = intervalHours === 24 ? 'every 24 hours (daily)' : `every ${intervalHours} hours`;
      textEl.innerHTML = `<strong>${candidateCount} contacts</strong> selected &rarr; <strong>${batchCount} ${batchWord}</strong> (${sizesStr}), carrying forward automatically <strong>${intervalText}</strong> without contact loss.`;
    }
  }

  // 4. Open Create Campaign Modal
  async function openCreateCampaignModal() {
    const modal = document.getElementById('campaignCreateModal');
    const form = document.getElementById('createCampaignForm');
    const errAlert = document.getElementById('createCampaignError');
    const templateSelect = document.getElementById('createTemplateSelect');
    const eligibleCountEl = document.getElementById('createEligibleCount');
    const totalCountEl = document.getElementById('createTotalCount');
    const excludedCountEl = document.getElementById('createExcludedCount');
    const previewBox = document.getElementById('createTemplatePreviewBox');

    if (form) form.reset();
    if (errAlert) errAlert.classList.add('hidden');
    if (previewBox) previewBox.classList.add('hidden');
    if (templateSelect) templateSelect.innerHTML = '<option value="">Loading approved templates...</option>';

    // Reset targeting state
    state.selectedLeadIds.clear();
    const cardTargetAll = document.getElementById('cardTargetAll');
    const cardTargetSpecific = document.getElementById('cardTargetSpecific');
    const targetAllRadio = document.getElementById('targetModeAll');
    const specificContainer = document.getElementById('specificLeadsContainer');
    if (targetAllRadio) targetAllRadio.checked = true;
    if (cardTargetAll) cardTargetAll.classList.add('active');
    if (cardTargetSpecific) cardTargetSpecific.classList.remove('active');
    if (specificContainer) specificContainer.classList.add('hidden');

    // Reset send mode state
    const cardSendImmediate = document.getElementById('cardSendImmediate');
    const cardSendScheduled = document.getElementById('cardSendScheduled');
    const sendImmRadio = document.getElementById('sendModeImmediate');
    const schedGroup = document.getElementById('campaignScheduleDateTimeGroup');
    if (sendImmRadio) sendImmRadio.checked = true;
    if (cardSendImmediate) cardSendImmediate.classList.add('active');
    if (cardSendScheduled) cardSendScheduled.classList.remove('active');
    if (schedGroup) schedGroup.classList.add('hidden');

    // Set default datetime on scheduler input (10 mins from now)
    const schedInput = document.getElementById('createScheduledAt');
    if (schedInput) {
      const now = new Date();
      now.setMinutes(now.getMinutes() + 10);
      const localIso = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
      schedInput.min = localIso;
      schedInput.value = localIso;
    }

    // Fetch approved templates, eligibility summary, and eligible leads in parallel
    try {
      const [tplRes, countRes, leadsRes] = await Promise.all([
        API.get('/api/templates?approval_status=APPROVED'),
        API.get('/api/campaigns/eligible-summary'),
        API.get('/api/campaigns/eligible-leads'),
      ]);

      if (tplRes && tplRes.ok) {
        const tplData = await tplRes.json();
        state.templates = tplData.items || [];
        if (state.templates.length === 0) {
          templateSelect.innerHTML = '<option value="">No Meta-approved templates found</option>';
        } else {
          templateSelect.innerHTML = '<option value="">-- Choose Approved Template --</option>' +
            state.templates.map(t => `<option value="${escapeHtml(t.template_name)}" data-lang="${escapeHtml(t.language)}">${escapeHtml(t.template_name)} (${escapeHtml(t.language)}) - ${escapeHtml(t.category)}</option>`).join('');
        }
      }

      if (countRes && countRes.ok) {
        const counts = await countRes.json();
        state.eligibleCount = counts.eligible_leads_count || 0;
        if (eligibleCountEl) eligibleCountEl.textContent = counts.eligible_leads_count.toLocaleString();
        if (totalCountEl) totalCountEl.textContent = counts.total_leads.toLocaleString();
        if (excludedCountEl) excludedCountEl.textContent = counts.excluded_leads_count.toLocaleString();
      }

      if (leadsRes && leadsRes.ok) {
        state.eligibleLeads = await leadsRes.json();
        renderSpecificLeadsList();
      }

      updateLiveBatchPlanPreview();
    } catch (e) {
      console.error('Error prefetching campaign creation dependencies:', e);
    }

    if (modal) modal.classList.remove('hidden');
  }

  // 5. Submit Create Campaign
  async function handleCreateCampaignSubmit(e) {
    e.preventDefault();
    const errAlert = document.getElementById('createCampaignError');
    const submitBtn = document.getElementById('saveCreateCampaignBtn');
    const nameInput = document.getElementById('createCampaignName');
    const templateSelect = document.getElementById('createTemplateSelect');
    const langInput = document.getElementById('createTemplateLanguage');
    const batchSizeInput = document.getElementById('createBatchSize');
    const maxRecipientsInput = document.getElementById('createMaxRecipients');
    const autoGenCheck = document.getElementById('createAutoGenerateBatches');

    if (errAlert) errAlert.classList.add('hidden');

    const name = nameInput.value.trim();
    const template = templateSelect.value;
    const language = langInput.value.trim() || 'en';
    const batchSize = parseInt(batchSizeInput.value, 10) || 50;
    const autoGenerate = autoGenCheck ? autoGenCheck.checked : true;
    const maxRecipients = maxRecipientsInput && maxRecipientsInput.value ? parseInt(maxRecipientsInput.value, 10) : null;
    const carryForwardInterval = parseInt(document.getElementById('createCarryForwardInterval')?.value, 10) || 0;

    if (!name) {
      if (errAlert) {
        errAlert.textContent = 'Campaign name is required.';
        errAlert.classList.remove('hidden');
      }
      return;
    }

    if (!template) {
      if (errAlert) {
        errAlert.textContent = 'Please select an approved WhatsApp template.';
        errAlert.classList.remove('hidden');
      }
      return;
    }

    if (batchSize < 1 || batchSize > 50) {
      if (errAlert) {
        errAlert.textContent = 'Batch size must be between 1 and 50 recipients.';
        errAlert.classList.remove('hidden');
      }
      return;
    }

    if (maxRecipients !== null && maxRecipients < 1) {
      if (errAlert) {
        errAlert.textContent = 'Max recipients limit must be at least 1.';
        errAlert.classList.remove('hidden');
      }
      return;
    }

    // Targeting mode validation
    let leadIds = null;
    const isSpecificMode = document.getElementById('targetModeSpecific')?.checked;
    if (isSpecificMode) {
      leadIds = Array.from(state.selectedLeadIds);
      if (leadIds.length === 0) {
        if (errAlert) {
          errAlert.textContent = 'Please select at least one candidate lead from the list or switch to All Eligible Leads.';
          errAlert.classList.remove('hidden');
        }
        return;
      }
    }

    // Send mode / Scheduling validation
    let scheduledAt = null;
    const isScheduledMode = document.getElementById('sendModeScheduled')?.checked;
    if (isScheduledMode) {
      const schedVal = document.getElementById('createScheduledAt')?.value;
      if (!schedVal) {
        if (errAlert) {
          errAlert.textContent = 'Please select a valid scheduled date and time.';
          errAlert.classList.remove('hidden');
        }
        return;
      }
      const schedDate = new Date(schedVal);
      if (isNaN(schedDate.getTime())) {
        if (errAlert) {
          errAlert.textContent = 'Invalid date/time format for campaign scheduling.';
          errAlert.classList.remove('hidden');
        }
        return;
      }
      scheduledAt = schedDate.toISOString();
    }

    try {
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Creating Campaign...';
      }

      const res = await API.post('/api/campaigns', {
        campaign_name: name,
        template_name: template,
        template_language: language,
        batch_size: batchSize,
        auto_generate_batches: autoGenerate,
        max_recipients: maxRecipients,
        lead_ids: leadIds,
        scheduled_at: scheduledAt,
        carry_forward_interval_hours: carryForwardInterval,
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to create campaign');
      }

      const created = await res.json();
      showToast(`Campaign '${created.campaign_name}' created successfully!`, 'success');

      // Close modal & reload campaigns
      const modal = document.getElementById('campaignCreateModal');
      if (modal) modal.classList.add('hidden');
      loadCampaigns();
    } catch (err) {
      if (errAlert) {
        errAlert.textContent = err.message || 'Error creating campaign.';
        errAlert.classList.remove('hidden');
      }
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Create Campaign';
      }
    }
  }

  // 6. Open Edit Campaign Modal
  async function openCampaignEdit(campaignId) {
    const modal = document.getElementById('campaignEditModal');
    const errAlert = document.getElementById('editCampaignError');
    const idInput = document.getElementById('editCampaignId');
    const nameInput = document.getElementById('editCampaignName');
    const langInput = document.getElementById('editTemplateLanguage');
    const templateSelect = document.getElementById('editTemplateSelect');

    if (errAlert) errAlert.classList.add('hidden');

    try {
      const [campRes, tplRes] = await Promise.all([
        API.get(`/api/campaigns/${campaignId}`),
        API.get('/api/templates?approval_status=APPROVED'),
      ]);

      if (!campRes.ok) throw new Error('Could not fetch campaign details');
      const camp = await campRes.json();

      if (idInput) idInput.value = camp.id;
      if (nameInput) nameInput.value = camp.campaign_name;
      if (langInput) langInput.value = camp.template_language;

      if (tplRes && tplRes.ok) {
        const tplData = await tplRes.json();
        const templates = tplData.items || [];
        templateSelect.innerHTML = templates.map(t =>
          `<option value="${escapeHtml(t.template_name)}" ${t.template_name === camp.template_name ? 'selected' : ''}>${escapeHtml(t.template_name)} (${escapeHtml(t.language)})</option>`
        ).join('');
      }

      if (modal) modal.classList.remove('hidden');
    } catch (err) {
      showToast(err.message || 'Failed to open edit dialog', 'error');
    }
  }

  // 7. Submit Edit Campaign
  async function handleEditCampaignSubmit(e) {
    e.preventDefault();
    const idInput = document.getElementById('editCampaignId');
    const nameInput = document.getElementById('editCampaignName');
    const templateSelect = document.getElementById('editTemplateSelect');
    const langInput = document.getElementById('editTemplateLanguage');
    const errAlert = document.getElementById('editCampaignError');
    const submitBtn = document.getElementById('saveEditCampaignBtn');

    const id = parseInt(idInput.value, 10);
    const name = nameInput.value.trim();
    const template = templateSelect.value;
    const language = langInput.value.trim() || 'en';

    try {
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Saving Changes...';
      }

      const res = await API.patch(`/api/campaigns/${id}`, {
        campaign_name: name,
        template_name: template,
        template_language: language,
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to update campaign');
      }

      showToast('Campaign updated successfully!', 'success');
      const modal = document.getElementById('campaignEditModal');
      if (modal) modal.classList.add('hidden');
      loadCampaigns();
    } catch (err) {
      if (errAlert) {
        errAlert.textContent = err.message || 'Error updating campaign.';
        errAlert.classList.remove('hidden');
      }
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Save Changes';
      }
    }
  }

  // 8. Open Campaign Details & Batches Breakdown
  async function openCampaignDetail(campaignId) {
    const modal = document.getElementById('campaignDetailModal');
    const title = document.getElementById('detailCampaignTitle');
    const statusBadge = document.getElementById('detailCampaignStatusBadge');
    const templateBadge = document.getElementById('detailCampaignTemplateBadge');
    const selEl = document.getElementById('detailTotalSelected');
    const eligEl = document.getElementById('detailTotalEligible');
    const exclEl = document.getElementById('detailTotalExcluded');
    const batchesCountEl = document.getElementById('detailBatchesCount');
    const batchesTbody = document.getElementById('detailBatchesTableBody');
    const partitionBtn = document.getElementById('detailPartitionBtn');

    if (modal) modal.classList.remove('hidden');
    if (batchesTbody) batchesTbody.innerHTML = '<tr><td colspan="7" class="text-center p-3">Loading batches...</td></tr>';

    try {
      const [campRes, batchesRes] = await Promise.all([
        API.get(`/api/campaigns/${campaignId}`),
        API.get(`/api/campaigns/${campaignId}/batches`),
      ]);

      if (!campRes.ok) throw new Error('Failed to load campaign');
      const camp = await campRes.json();
      const batches = batchesRes.ok ? (await batchesRes.json()).items || [] : [];

      state.activeCampaign = camp;

      const campDisplayName = getCampaignDisplayName(camp.campaign_name);
      const tplDisplayName = getTemplateDisplayName(camp.template_name);

      if (title) title.textContent = campDisplayName;
      if (statusBadge) statusBadge.innerHTML = getCampaignStatusBadge(camp.status);
      if (templateBadge) templateBadge.textContent = `${tplDisplayName} (${camp.template_name} • ${camp.template_language})`;
      if (selEl) selEl.textContent = camp.total_leads_selected;
      if (eligEl) eligEl.textContent = camp.total_leads_eligible;
      if (exclEl) exclEl.textContent = camp.total_leads_excluded;
      if (batchesCountEl) batchesCountEl.textContent = `${batches.length} Batches`;

      if (partitionBtn) {
        partitionBtn.setAttribute('data-id', camp.id);
        partitionBtn.style.display = camp.status === 'Draft' || batches.length === 0 ? 'inline-flex' : 'none';
      }

      if (batches.length === 0) {
        batchesTbody.innerHTML = `
          <tr>
            <td colspan="7" class="text-center p-4 text-muted">
              No batches generated yet. Click "Partition Remaining Leads" to chunk eligible opted-in contacts into batches of 50.
            </td>
          </tr>
        `;
        return;
      }

      batchesTbody.innerHTML = batches.map(b => `
        <tr>
          <td><strong>Batch #${b.batch_number}</strong></td>
          <td>${b.batch_size} Recipients</td>
          <td>${getBatchApprovalBadge(b.approval_status)}</td>
          <td>${getBatchSendBadge(b.send_status)}</td>
          <td>
            <span style="color: var(--success); font-weight: 600;">${b.sent_messages_count} sent</span> /
            <span style="color: var(--danger);">${b.failed_messages_count} failed</span>
          </td>
          <td><small class="text-muted">${formatDateTime(b.created_at)}</small></td>
          <td class="text-right">
            <div class="row-actions-group">
              <button class="btn-table-action" data-batch-action="review" data-campaign-id="${camp.id}" data-batch-id="${b.id}" title="Review Recipients">
                Recipients
              </button>
              ${b.approval_status === 'PENDING_APPROVAL' || b.approval_status === 'Pending' ? `
                <button class="btn-table-action btn-action-success" data-batch-action="approve" data-campaign-id="${camp.id}" data-batch-id="${b.id}" title="Approve this batch">
                  Approve
                </button>
                <button class="btn-table-action btn-action-danger" data-batch-action="reject" data-campaign-id="${camp.id}" data-batch-id="${b.id}" title="Reject this batch">
                  Reject
                </button>
              ` : ''}
              ${b.approval_status === 'Approved' && b.send_status === 'Pending' ? `
                <button class="btn-table-action btn-action-primary" data-batch-action="send" data-campaign-id="${camp.id}" data-batch-id="${b.id}" title="Send batch messages">
                  Send
                </button>
              ` : ''}
            </div>
          </td>
        </tr>
      `).join('');

      // Attach batch sub-table action listeners
      batchesTbody.querySelectorAll('button[data-batch-action]').forEach(btn => {
        btn.addEventListener('click', () => {
          const act = btn.getAttribute('data-batch-action');
          const cId = parseInt(btn.getAttribute('data-campaign-id'), 10);
          const bId = parseInt(btn.getAttribute('data-batch-id'), 10);
          if (act === 'review') {
            if (window.ApprovalsManager) {
              window.ApprovalsManager.openBatchReview(cId, bId);
            }
          } else if (act === 'approve') {
            handleBatchApproval(cId, bId);
          } else if (act === 'reject') {
            handleBatchRejection(cId, bId);
          } else if (act === 'send') {
            handleBatchSend(cId, bId);
          }
        });
      });
    } catch (err) {
      showToast(err.message || 'Failed to load campaign details', 'error');
    }
  }

  // 9. Generate Batches for campaign
  async function handleGenerateBatches(campaignId) {
    if (!confirm('Evaluate all opted-in leads and partition them into batches of 50?')) return;

    try {
      const res = await API.post(`/api/campaigns/${campaignId}/generate-batches`, {
        batch_size: 50,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to partition batches');
      }

      const data = await res.json();
      showToast(`Generated ${data.total} new batches for review!`, 'success');
      loadCampaigns();
      if (state.activeCampaign && state.activeCampaign.id === campaignId) {
        openCampaignDetail(campaignId);
      }
    } catch (err) {
      showToast(err.message || 'Error generating batches', 'error');
    }
  }

  // 10. Approve Batch from campaign view
  async function handleBatchApproval(campaignId, batchId) {
    if (!confirm(`Confirm approval for Batch #${batchId}? Only approved batches can be dispatched.`)) return;

    try {
      const res = await API.post(`/api/campaigns/${campaignId}/batches/${batchId}/approve`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Approval failed');
      }
      showToast('Batch approved successfully!', 'success');
      openCampaignDetail(campaignId);
      loadCampaigns();
    } catch (err) {
      showToast(err.message || 'Error approving batch', 'error');
    }
  }

  // 11. Reject Batch from campaign view
  async function handleBatchRejection(campaignId, batchId) {
    if (!confirm(`Are you sure you want to REJECT Batch #${batchId}? Rejected batches cannot be sent.`)) return;

    try {
      const res = await API.post(`/api/campaigns/${campaignId}/batches/${batchId}/reject`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Rejection failed');
      }
      showToast('Batch rejected.', 'success');
      openCampaignDetail(campaignId);
      loadCampaigns();
    } catch (err) {
      showToast(err.message || 'Error rejecting batch', 'error');
    }
  }

  // 12. Send Batch from campaign view
  async function handleBatchSend(campaignId, batchId) {
    if (!confirm(`Dispatch WhatsApp template messages to all consented recipients in Batch #${batchId}? (Notice: In OFFLINE mode messages will be simulated safely).`)) return;

    try {
      const res = await API.post(`/api/campaigns/${campaignId}/batches/${batchId}/send`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Dispatch failed');
      }
      const data = await res.json();
      showToast(`Batch dispatch initiated: ${data.sent_count} sent, ${data.failed_count} failed.`, 'success');
      openCampaignDetail(campaignId);
      loadCampaigns();
    } catch (err) {
      showToast(err.message || 'Error dispatching batch', 'error');
    }
  }

  // =========================================================================
  // 12. WhatsApp Template Builder & Template Manager
  // =========================================================================

  function openCreateTemplateModal() {
    const modal = document.getElementById('templateCreateModal');
    const form = document.getElementById('createTemplateForm');
    const errAlert = document.getElementById('createTemplateError');
    const nameInput = document.getElementById('newTemplateName');
    const langInput = document.getElementById('newTemplateLanguage');
    const catSelect = document.getElementById('newTemplateCategory');
    const headerTypeSelect = document.getElementById('newTemplateHeaderType');
    const headerTextInput = document.getElementById('newTemplateHeaderText');
    const bodyInput = document.getElementById('newTemplateBodyText');
    const headerTextGroup = document.getElementById('newTemplateHeaderTextGroup');
    const headerImageGroup = document.getElementById('newTemplateImageGroup');
    const previewImg = document.getElementById('whatsappPreviewHeaderImg');
    const previewText = document.getElementById('whatsappPreviewHeaderText');
    const previewBody = document.getElementById('whatsappPreviewBodyText');
    const thumbContainer = document.getElementById('templateImagePreviewContainer');
    const uploadedPath = document.getElementById('uploadedImagePath');

    if (form) form.reset();
    if (errAlert) errAlert.classList.add('hidden');
    if (uploadedPath) uploadedPath.value = '';
    if (thumbContainer) thumbContainer.classList.add('hidden');
    if (previewImg) { previewImg.src = ''; previewImg.classList.add('hidden'); }
    if (previewText) { previewText.textContent = ''; previewText.classList.add('hidden'); }
    if (previewBody) previewBody.textContent = 'Your message preview will appear here as you type...';
    if (headerTextGroup) headerTextGroup.classList.add('hidden');
    if (headerImageGroup) headerImageGroup.classList.remove('hidden');

    if (nameInput) nameInput.value = '';
    if (langInput) langInput.value = 'en';
    if (catSelect) catSelect.value = 'MARKETING';
    if (headerTypeSelect) headerTypeSelect.value = 'IMAGE';

    updateWhatsAppPreview();
    if (modal) modal.classList.remove('hidden');
  }

  function updateWhatsAppPreview() {
    const headerType = document.getElementById('newTemplateHeaderType')?.value || 'IMAGE';
    const headerText = document.getElementById('newTemplateHeaderText')?.value || '';
    const bodyText = document.getElementById('newTemplateBodyText')?.value || '';
    const previewImg = document.getElementById('whatsappPreviewHeaderImg');
    const previewText = document.getElementById('whatsappPreviewHeaderText');
    const previewBody = document.getElementById('whatsappPreviewBodyText');
    const uploadedPath = document.getElementById('uploadedImagePath')?.value;

    if (headerType === 'IMAGE' && uploadedPath) {
      if (previewImg) {
        let url = uploadedPath;
        if (url.includes('data/uploads/')) {
          url = '/' + url.substring(url.indexOf('data/uploads/') + 5);
        } else if (!url.startsWith('/')) {
          url = '/' + url;
        }
        previewImg.src = url;
        previewImg.classList.remove('hidden');
      }
      if (previewText) previewText.classList.add('hidden');
    } else if (headerType === 'TEXT' && headerText.trim()) {
      if (previewText) {
        previewText.textContent = headerText;
        previewText.classList.remove('hidden');
      }
      if (previewImg) previewImg.classList.add('hidden');
    } else {
      if (previewImg) previewImg.classList.add('hidden');
      if (previewText) previewText.classList.add('hidden');
    }

    if (previewBody) {
      if (!bodyText.trim()) {
        previewBody.innerHTML = '<span style="color: #94a3b8; font-style: italic;">Type your body text above to preview...</span>';
      } else {
        let formatted = escapeHtml(bodyText);
        formatted = formatted.replace(/\{\{(\d+)\}\}/g, '<span class="whatsapp-variable-tag">{{$1}}</span>');
        previewBody.innerHTML = formatted;
      }
    }
  }

  async function handleTemplateImageUpload(file) {
    const errAlert = document.getElementById('createTemplateError');
    if (errAlert) errAlert.classList.add('hidden');

    if (!file) return;

    const allowedTypes = ['image/jpeg', 'image/png', 'image/jpg'];
    const ext = file.name.split('.').pop().toLowerCase();
    const allowedExts = ['jpg', 'jpeg', 'png'];

    if (!allowedTypes.includes(file.type.toLowerCase()) || !allowedExts.includes(ext)) {
      const errMsg = `Prohibited file format (${file.type || ext}). Only JPG and PNG image files are permitted. PDFs, documents, and videos are strictly rejected.`;
      if (errAlert) {
        errAlert.textContent = errMsg;
        errAlert.classList.remove('hidden');
      }
      showToast(errMsg, 'error');
      return;
    }

    if (file.size > 5 * 1024 * 1024) {
      const errMsg = `File exceeds the 5MB limit (${(file.size / (1024 * 1024)).toFixed(2)}MB). Please choose a smaller image.`;
      if (errAlert) {
        errAlert.textContent = errMsg;
        errAlert.classList.remove('hidden');
      }
      showToast(errMsg, 'error');
      return;
    }

    try {
      const formData = new FormData();
      formData.append('file', file);

      const res = await API.post('/api/templates/upload-image', formData);
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || 'Image upload failed');
      }

      const data = await res.json();
      const uploadedPath = document.getElementById('uploadedImagePath');
      const thumb = document.getElementById('templateImageThumb');
      const thumbContainer = document.getElementById('templateImagePreviewContainer');

      if (uploadedPath) uploadedPath.value = data.image_path;
      if (thumb) thumb.src = data.image_url;
      if (thumbContainer) thumbContainer.classList.remove('hidden');

      updateWhatsAppPreview();
      showToast('Header image uploaded successfully!', 'success');
    } catch (err) {
      console.error('Image upload error:', err);
      if (errAlert) {
        errAlert.textContent = err.message || 'Image upload failed';
        errAlert.classList.remove('hidden');
      }
      showToast(err.message || 'Image upload failed', 'error');
    }
  }

  async function handleCreateTemplateSubmit(e) {
    e.preventDefault();
    const errAlert = document.getElementById('createTemplateError');
    const submitBtn = document.getElementById('saveCreateTemplateBtn');
    const nameInput = document.getElementById('newTemplateName');
    const catSelect = document.getElementById('newTemplateCategory');
    const langInput = document.getElementById('newTemplateLanguage');
    const headerTypeSelect = document.getElementById('newTemplateHeaderType');
    const headerTextInput = document.getElementById('newTemplateHeaderText');
    const bodyInput = document.getElementById('newTemplateBodyText');
    const uploadedPath = document.getElementById('uploadedImagePath');

    if (errAlert) errAlert.classList.add('hidden');

    const name = nameInput.value.trim().toLowerCase();
    const category = catSelect.value;
    const language = langInput.value.trim() || 'en';
    const headerType = headerTypeSelect.value;
    const headerText = headerTextInput ? headerTextInput.value.trim() : null;
    const bodyText = bodyInput.value.trim();
    const imagePath = uploadedPath ? uploadedPath.value : null;

    if (!name) {
      errAlert.textContent = 'Template identifier name is required.';
      errAlert.classList.remove('hidden');
      return;
    }

    if (!/^[a-z0-9_]+$/.test(name)) {
      errAlert.textContent = 'Template name must contain only lowercase letters, numbers, and underscores (e.g. summer_promo_2026).';
      errAlert.classList.remove('hidden');
      return;
    }

    if (!bodyText) {
      errAlert.textContent = 'Template body text is required.';
      errAlert.classList.remove('hidden');
      return;
    }

    if (headerType === 'IMAGE' && !imagePath) {
      errAlert.textContent = 'Please upload a header image or change Header Media Format to NONE.';
      errAlert.classList.remove('hidden');
      return;
    }

    try {
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Submitting Template...';
      }

      const res = await API.post('/api/templates', {
        template_name: name,
        category: category,
        language: language,
        header_type: headerType === 'NONE' ? null : headerType,
        header_text: headerType === 'TEXT' ? headerText : null,
        header_image_path: headerType === 'IMAGE' ? imagePath : null,
        body_text: bodyText,
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to submit template');
      }

      const created = await res.json();
      showToast(`Template '${created.template_name}' registered successfully! (Status: ${created.approval_status})`, 'success');

      const modal = document.getElementById('templateCreateModal');
      if (modal) modal.classList.add('hidden');

      loadManageTemplates();
    } catch (err) {
      if (errAlert) {
        errAlert.textContent = err.message || 'Error creating template.';
        errAlert.classList.remove('hidden');
      }
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Create & Submit Template';
      }
    }
  }

  function openManageTemplatesModal() {
    const modal = document.getElementById('templateManageModal');
    if (modal) modal.classList.remove('hidden');
    loadManageTemplates();
  }

  async function loadManageTemplates() {
    const tbody = document.getElementById('manageTemplatesTableBody');
    const emptyState = document.getElementById('manageTemplatesEmptyState');
    if (tbody) tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; padding: 1.5rem;">Loading templates...</td></tr>';

    try {
      const res = await API.get('/api/templates');
      if (!res || !res.ok) throw new Error('Failed to fetch templates');

      const data = await res.json();
      const templates = data.items || [];

      if (templates.length === 0) {
        if (tbody) tbody.innerHTML = '';
        if (emptyState) emptyState.classList.remove('hidden');
        return;
      }

      if (emptyState) emptyState.classList.add('hidden');
      if (tbody) {
        tbody.innerHTML = templates.map(t => {
          const isPending = t.approval_status === 'PENDING';
          const isApproved = t.approval_status === 'APPROVED';
          const badgeClass = isApproved ? 'badge-template-approved' : (isPending ? 'badge-template-pending' : 'badge-template-rejected');

          return `
            <tr>
              <td><strong>${escapeHtml(t.template_name)}</strong></td>
              <td><span class="badge" style="background: #f1f5f9; color: #334155;">${escapeHtml(t.category)}</span></td>
              <td><code>${escapeHtml(t.language)}</code></td>
              <td>
                ${t.header_type === 'IMAGE' ? `
                  <span class="badge" style="background: #eff6ff; color: #1d4ed8;">Image Header</span>
                  ${t.header_image_url ? `<a href="${escapeHtml(t.header_image_url)}" target="_blank" style="margin-left: 0.35rem; font-size: 0.75rem;">View</a>` : ''}
                ` : (t.header_type === 'TEXT' ? `<span>Text: "${escapeHtml(t.header_text || '')}"</span>` : '<span class="text-muted">None</span>')}
              </td>
              <td>
                <span class="badge ${badgeClass}">${escapeHtml(t.approval_status)}</span>
              </td>
              <td class="text-right">
                ${isPending ? `
                  <button class="btn-xs btn-action-success" data-action="mock-approve" data-id="${t.id}" title="Approve locally for testing in mock mode">
                    Approve Locally (Mock)
                  </button>
                ` : ''}
              </td>
            </tr>
          `;
        }).join('');

        tbody.querySelectorAll('button[data-action="mock-approve"]').forEach(btn => {
          btn.addEventListener('click', async () => {
            const tId = btn.getAttribute('data-id');
            await handleMockApproveTemplate(tId);
          });
        });
      }
    } catch (err) {
      console.error('Error loading manage templates:', err);
      if (tbody) tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--danger); padding: 1.5rem;">${escapeHtml(err.message)}</td></tr>`;
    }
  }

  async function handleMockApproveTemplate(templateId) {
    try {
      const res = await API.post(`/api/templates/${templateId}/mock-approve`, {});
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Mock approval failed');
      }
      showToast('Template approved locally in mock mode!', 'success');
      loadManageTemplates();
    } catch (e) {
      showToast(e.message || 'Mock approval failed', 'error');
    }
  }

  async function handleSyncMetaTemplates() {
    const modalBtn = document.getElementById('syncMetaTemplatesBtn');
    const headerBtn = document.getElementById('syncMetaTemplatesHeaderBtn');
    const activeBtns = [modalBtn, headerBtn].filter(Boolean);

    try {
      activeBtns.forEach(b => {
        b.disabled = true;
        b.dataset.prevHtml = b.innerHTML;
        b.textContent = 'Syncing...';
      });

      const res = await API.post('/api/templates/sync', {});
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        if (res.status === 401 || (err.detail && err.detail.includes('190'))) {
          throw new Error('Meta Access Token is expired or invalid (Error 190). Please update WHATSAPP_ACCESS_TOKEN in .env with a permanent System User token and restart the server.');
        }
        throw new Error(err.detail || 'Meta template sync failed');
      }

      const data = await res.json();
      if (data.mock_mode) {
        showToast(data.message || 'Meta Cloud API integration is disabled in .env (WHATSAPP_ENABLED=False). Operating in local development mock mode.', 'info');
      } else {
        showToast(data.message || 'Meta templates synced successfully!', 'success');
      }

      // Refresh manage modal if open
      const manageModal = document.getElementById('templateManageModal');
      if (manageModal && !manageModal.classList.contains('hidden')) {
        loadManageTemplates();
      }
      loadTemplates();
    } catch (e) {
      console.error('Meta template sync error:', e);
      showToast(e.message || 'Error syncing templates from Meta', 'error');
    } finally {
      activeBtns.forEach(b => {
        b.disabled = false;
        if (b.dataset.prevHtml) {
          b.innerHTML = b.dataset.prevHtml;
        } else {
          b.innerHTML = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"></polyline><polyline points="1 20 1 14 7 14"></polyline><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg> Sync Status from Meta`;
        }
      });
    }
  }

  // 13. Init Controller
  function init() {
    if (state.initialized) {
      loadCampaigns();
      return;
    }
    state.initialized = true;

    // Header buttons
    const refreshBtn = document.getElementById('refreshCampaignsBtn');
    if (refreshBtn) refreshBtn.addEventListener('click', loadCampaigns);

    const openCreateBtn = document.getElementById('openCreateCampaignModalBtn');
    if (openCreateBtn) openCreateBtn.addEventListener('click', openCreateCampaignModal);

    const emptyNewBtn = document.getElementById('campaignsEmptyNewBtn');
    if (emptyNewBtn) emptyNewBtn.addEventListener('click', openCreateCampaignModal);

    const openManageTplBtn = document.getElementById('openManageTemplatesModalBtn');
    if (openManageTplBtn) openManageTplBtn.addEventListener('click', openManageTemplatesModal);

    const syncMetaHeaderBtn = document.getElementById('syncMetaTemplatesHeaderBtn');
    if (syncMetaHeaderBtn) syncMetaHeaderBtn.addEventListener('click', handleSyncMetaTemplates);

    const openCreateTplBtn = document.getElementById('openCreateTemplateModalBtn');
    if (openCreateTplBtn) openCreateTplBtn.addEventListener('click', openCreateTemplateModal);

    const openCreateFromManageBtn = document.getElementById('openCreateFromManageBtn');
    if (openCreateFromManageBtn) openCreateFromManageBtn.addEventListener('click', openCreateTemplateModal);

    const syncMetaTplBtn = document.getElementById('syncMetaTemplatesBtn');
    if (syncMetaTplBtn) syncMetaTplBtn.addEventListener('click', handleSyncMetaTemplates);

    // Modal dismiss buttons
    const closeCreateTplBtn = document.getElementById('closeCreateTemplateModalBtn');
    const cancelCreateTplBtn = document.getElementById('cancelCreateTemplateBtn');
    const tplModal = document.getElementById('templateCreateModal');
    [closeCreateTplBtn, cancelCreateTplBtn].forEach(b => {
      if (b && tplModal) b.addEventListener('click', () => tplModal.classList.add('hidden'));
    });

    const closeManageTplBtn = document.getElementById('closeManageTemplatesModalBtn');
    const closeManageTplBottomBtn = document.getElementById('closeManageTemplatesBottomBtn');
    const manageModal = document.getElementById('templateManageModal');
    [closeManageTplBtn, closeManageTplBottomBtn].forEach(b => {
      if (b && manageModal) b.addEventListener('click', () => manageModal.classList.add('hidden'));
    });

    // Template Creator inputs & Preview wiring
    const createTplForm = document.getElementById('createTemplateForm');
    if (createTplForm) createTplForm.addEventListener('submit', handleCreateTemplateSubmit);

    const newTplNameInput = document.getElementById('newTemplateName');
    if (newTplNameInput) {
      newTplNameInput.addEventListener('input', () => {
        newTplNameInput.value = newTplNameInput.value.toLowerCase().replace(/[^a-z0-9_]/g, '');
      });
    }

    const newTplHeaderType = document.getElementById('newTemplateHeaderType');
    const headerTextGroup = document.getElementById('newTemplateHeaderTextGroup');
    const headerImageGroup = document.getElementById('newTemplateImageGroup');
    if (newTplHeaderType) {
      newTplHeaderType.addEventListener('change', () => {
        const val = newTplHeaderType.value;
        if (val === 'IMAGE') {
          if (headerImageGroup) headerImageGroup.classList.remove('hidden');
          if (headerTextGroup) headerTextGroup.classList.add('hidden');
        } else if (val === 'TEXT') {
          if (headerImageGroup) headerImageGroup.classList.add('hidden');
          if (headerTextGroup) headerTextGroup.classList.remove('hidden');
        } else {
          if (headerImageGroup) headerImageGroup.classList.add('hidden');
          if (headerTextGroup) headerTextGroup.classList.add('hidden');
        }
        updateWhatsAppPreview();
      });
    }

    const newTplHeaderText = document.getElementById('newTemplateHeaderText');
    if (newTplHeaderText) newTplHeaderText.addEventListener('input', updateWhatsAppPreview);

    const newTplBodyText = document.getElementById('newTemplateBodyText');
    if (newTplBodyText) newTplBodyText.addEventListener('input', updateWhatsAppPreview);

    // Image upload dropzone
    const imgDropZone = document.getElementById('templateImageDropZone');
    const imgFileInput = document.getElementById('templateImageInput');
    const removeImgBtn = document.getElementById('removeTemplateImageBtn');
    const uploadedPath = document.getElementById('uploadedImagePath');
    const imgThumbContainer = document.getElementById('templateImagePreviewContainer');
    const previewImg = document.getElementById('whatsappPreviewHeaderImg');

    if (imgDropZone && imgFileInput) {
      imgDropZone.addEventListener('click', () => imgFileInput.click());
      imgDropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        imgDropZone.style.borderColor = 'var(--primary)';
      });
      imgDropZone.addEventListener('dragleave', () => {
        imgDropZone.style.borderColor = '#cbd5e1';
      });
      imgDropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        imgDropZone.style.borderColor = '#cbd5e1';
        if (e.dataTransfer && e.dataTransfer.files.length > 0) {
          handleTemplateImageUpload(e.dataTransfer.files[0]);
        }
      });
      imgFileInput.addEventListener('change', (e) => {
        if (e.target.files && e.target.files.length > 0) {
          handleTemplateImageUpload(e.target.files[0]);
        }
      });
    }

    if (removeImgBtn) {
      removeImgBtn.addEventListener('click', () => {
        if (uploadedPath) uploadedPath.value = '';
        if (imgThumbContainer) imgThumbContainer.classList.add('hidden');
        if (previewImg) { previewImg.src = ''; previewImg.classList.add('hidden'); }
        if (imgFileInput) imgFileInput.value = '';
        updateWhatsAppPreview();
      });
    }

    // Dynamic Batch Plan Preview inputs
    const batchSizeInput = document.getElementById('createBatchSize');
    if (batchSizeInput) batchSizeInput.addEventListener('input', updateLiveBatchPlanPreview);

    const maxRecipientsInput = document.getElementById('createMaxRecipients');
    if (maxRecipientsInput) maxRecipientsInput.addEventListener('input', updateLiveBatchPlanPreview);

    const intervalSelect = document.getElementById('createCarryForwardInterval');
    if (intervalSelect) intervalSelect.addEventListener('change', updateLiveBatchPlanPreview);

    // Filter controls
    const searchInput = document.getElementById('campaignSearchInput');
    if (searchInput) {
      searchInput.addEventListener('input', () => {
        state.search = searchInput.value;
        loadCampaigns();
      });
    }

    const statusFilter = document.getElementById('campaignStatusFilter');
    if (statusFilter) {
      statusFilter.addEventListener('change', () => {
        state.statusFilter = statusFilter.value;
        state.page = 1;
        loadCampaigns();
      });
    }

    const resetFiltersBtn = document.getElementById('resetCampaignFiltersBtn');
    if (resetFiltersBtn) {
      resetFiltersBtn.addEventListener('click', () => {
        if (searchInput) searchInput.value = '';
        if (statusFilter) statusFilter.value = '';
        state.search = '';
        state.statusFilter = '';
        state.page = 1;
        loadCampaigns();
      });
    }

    // Pagination buttons
    const prevBtn = document.getElementById('campaignsPrevBtn');
    if (prevBtn) {
      prevBtn.addEventListener('click', () => {
        if (state.page > 1) {
          state.page--;
          loadCampaigns();
        }
      });
    }

    const nextBtn = document.getElementById('campaignsNextBtn');
    if (nextBtn) {
      nextBtn.addEventListener('click', () => {
        if (state.page < state.totalPages) {
          state.page++;
          loadCampaigns();
        }
      });
    }

    const pageSizeSelect = document.getElementById('campaignsPageSizeSelect');
    if (pageSizeSelect) {
      pageSizeSelect.addEventListener('change', () => {
        state.pageSize = parseInt(pageSizeSelect.value, 10);
        state.page = 1;
        loadCampaigns();
      });
    }

    // Modal Close Buttons
    const closeCreateBtn = document.getElementById('closeCreateCampaignModalBtn');
    const cancelCreateBtn = document.getElementById('cancelCreateCampaignBtn');
    const createModal = document.getElementById('campaignCreateModal');
    [closeCreateBtn, cancelCreateBtn].forEach(b => {
      if (b) b.addEventListener('click', () => createModal.classList.add('hidden'));
    });

    const closeEditBtn = document.getElementById('closeEditCampaignModalBtn');
    const cancelEditBtn = document.getElementById('cancelEditCampaignBtn');
    const editModal = document.getElementById('campaignEditModal');
    [closeEditBtn, cancelEditBtn].forEach(b => {
      if (b) b.addEventListener('click', () => editModal.classList.add('hidden'));
    });

    const closeDetailBtn = document.getElementById('closeCampaignDetailBtn');
    const detailModal = document.getElementById('campaignDetailModal');
    if (closeDetailBtn) {
      closeDetailBtn.addEventListener('click', () => detailModal.classList.add('hidden'));
    }

    // Form submissions
    const createForm = document.getElementById('createCampaignForm');
    if (createForm) createForm.addEventListener('submit', handleCreateCampaignSubmit);

    // Template preview listener
    const createTemplateSelect = document.getElementById('createTemplateSelect');
    if (createTemplateSelect) {
      createTemplateSelect.addEventListener('change', (e) => {
        renderTemplatePreview(e.target.value);
      });
    }

    // Targeting mode toggle
    const targetAllRadio = document.getElementById('targetModeAll');
    const targetSpecificRadio = document.getElementById('targetModeSpecific');
    const cardTargetAll = document.getElementById('cardTargetAll');
    const cardTargetSpecific = document.getElementById('cardTargetSpecific');
    const specificContainer = document.getElementById('specificLeadsContainer');

    if (targetAllRadio && targetSpecificRadio) {
      targetAllRadio.addEventListener('change', () => {
        if (targetAllRadio.checked) {
          if (cardTargetAll) cardTargetAll.classList.add('active');
          if (cardTargetSpecific) cardTargetSpecific.classList.remove('active');
          if (specificContainer) specificContainer.classList.add('hidden');
        }
      });
      targetSpecificRadio.addEventListener('change', () => {
        if (targetSpecificRadio.checked) {
          if (cardTargetSpecific) cardTargetSpecific.classList.add('active');
          if (cardTargetAll) cardTargetAll.classList.remove('active');
          if (specificContainer) specificContainer.classList.remove('hidden');
        }
      });
    }

    // Specific leads search & selection
    const specificSearch = document.getElementById('specificLeadsSearch');
    if (specificSearch) {
      specificSearch.addEventListener('input', (e) => {
        renderSpecificLeadsList(e.target.value);
      });
    }

    const selectAllBtn = document.getElementById('selectAllSpecificLeadsBtn');
    if (selectAllBtn) {
      selectAllBtn.addEventListener('click', () => {
        (state.eligibleLeads || []).forEach(l => state.selectedLeadIds.add(l.id));
        renderSpecificLeadsList(specificSearch ? specificSearch.value : '');
      });
    }

    const deselectAllBtn = document.getElementById('deselectAllSpecificLeadsBtn');
    if (deselectAllBtn) {
      deselectAllBtn.addEventListener('click', () => {
        state.selectedLeadIds.clear();
        renderSpecificLeadsList(specificSearch ? specificSearch.value : '');
      });
    }

    const specificList = document.getElementById('specificLeadsList');
    if (specificList) {
      specificList.addEventListener('change', (e) => {
        if (e.target && e.target.classList.contains('lead-select-checkbox')) {
          const lId = parseInt(e.target.value, 10);
          if (e.target.checked) {
            state.selectedLeadIds.add(lId);
          } else {
            state.selectedLeadIds.delete(lId);
          }
          const countEl = document.getElementById('specificLeadsSelectedCount');
          if (countEl) countEl.textContent = state.selectedLeadIds.size.toLocaleString();
        }
      });
    }

    // Send mode toggle
    const sendImmRadio = document.getElementById('sendModeImmediate');
    const sendSchedRadio = document.getElementById('sendModeScheduled');
    const cardSendImm = document.getElementById('cardSendImmediate');
    const cardSendSched = document.getElementById('cardSendScheduled');
    const schedGroup = document.getElementById('campaignScheduleDateTimeGroup');

    if (sendImmRadio && sendSchedRadio) {
      sendImmRadio.addEventListener('change', () => {
        if (sendImmRadio.checked) {
          if (cardSendImm) cardSendImm.classList.add('active');
          if (cardSendSched) cardSendSched.classList.remove('active');
          if (schedGroup) schedGroup.classList.add('hidden');
        }
      });
      sendSchedRadio.addEventListener('change', () => {
        if (sendSchedRadio.checked) {
          if (cardSendSched) cardSendSched.classList.add('active');
          if (cardSendImm) cardSendImm.classList.remove('active');
          if (schedGroup) schedGroup.classList.remove('hidden');
        }
      });
    }

    const editForm = document.getElementById('editCampaignForm');
    if (editForm) editForm.addEventListener('submit', handleEditCampaignSubmit);

    const partitionBtn = document.getElementById('detailPartitionBtn');
    if (partitionBtn) {
      partitionBtn.addEventListener('click', () => {
        const cId = parseInt(partitionBtn.getAttribute('data-id'), 10);
        if (cId) handleGenerateBatches(cId);
      });
    }

    loadCampaigns();
  }

  // Export to window
  window.CampaignsManager = {
    init,
    loadCampaigns,
    openCampaignDetail,
    openCampaignEdit,
    openCreateTemplateModal,
    openManageTemplatesModal,
  };
})();
