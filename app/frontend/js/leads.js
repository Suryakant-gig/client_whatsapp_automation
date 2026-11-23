/**
 * Lead Management Module Controller (Phase 9.4)
 * Provides searchable, filterable, paginated directory of customer leads,
 * comprehensive lead details modal with follow-up schedules and interaction history,
 * in-place lead editing, and WhatsApp consent compliance management.
 */

(function () {
  const state = {
    page: 1,
    pageSize: 50,
    search: '',
    status: '',
    optInStatus: '',
    followupPaused: '',
    sortBy: 'created_at',
    sortOrder: 'desc',
    total: 0,
    totalPages: 0,
    items: [],
    initialized: false,
    debounceTimer: null,
    activeLeadDetail: null,
    queueTab: 'all', // 'all' or 'interested'
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

  // Helper: Format UTC datetime
  function formatDateTime(isoString) {
    if (!isoString) return 'None';
    try {
      const d = new Date(isoString);
      if (isNaN(d.getTime())) return String(isoString);
      return d.toISOString().replace('T', ' ').substring(0, 19) + ' UTC';
    } catch {
      return String(isoString);
    }
  }

  // Helper: Format IST datetime for sales agents
  function formatDateTimeIST(isoString) {
    if (!isoString) return 'None';
    try {
      let s = String(isoString).trim();
      if (!s.endsWith('Z') && !/[+-]\d{2}:\d{2}$/.test(s)) {
        s = s.replace(' ', 'T') + 'Z';
      }
      const d = new Date(s);
      if (isNaN(d.getTime())) return String(isoString);
      return d.toLocaleString('en-IN', {
        timeZone: 'Asia/Kolkata',
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        hour12: true,
      }) + ' IST';
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

  // Status badge helpers
  function getLeadStatusBadge(status) {
    const s = escapeHtml(status || 'Pending');
    if (status === 'Interested') return `<span class="badge badge-interested">Interested</span>`;
    if (status === 'Pending') return `<span class="badge badge-pending">Pending</span>`;
    if (status === 'Replied') return `<span class="badge badge-replied">Replied</span>`;
    if (status === 'Not Interested') return `<span class="badge badge-not-interested">Not Interested</span>`;
    return `<span class="badge">${s}</span>`;
  }

  function getConsentBadge(consent) {
    const c = escapeHtml(consent || 'NOT_OPTED_IN');
    if (consent === 'OPTED_IN') return `<span class="badge badge-opted-in">OPTED_IN</span>`;
    if (consent === 'NOT_OPTED_IN') return `<span class="badge badge-not-opted">NOT_OPTED_IN</span>`;
    if (consent === 'OPTED_OUT') return `<span class="badge badge-opted-out">OPTED_OUT</span>`;
    return `<span class="badge">${c}</span>`;
  }

  function getFollowupBadge(isPaused) {
    if (isPaused) {
      return `<span class="badge badge-paused">Paused</span>`;
    }
    return `<span class="badge badge-active">Active</span>`;
  }

  // Live count for pending manual calls badge
  async function updatePendingCallsBadge() {
    try {
      const res = await API.get('/api/leads?needs_manual_followup=true&page_size=1');
      if (res && res.ok) {
        const data = await res.json();
        const count = data.total || 0;
        const badge = document.getElementById('interestedQueueBadge');
        if (badge) {
          badge.textContent = count;
          badge.classList.toggle('empty', count === 0);
        }
      }
    } catch (e) {
      console.warn('Failed to update pending calls badge count', e);
    }
  }

  // 1. Fetch and render leads table
  async function loadLeads() {
    const tbody = document.getElementById('leadsTableBody');
    const loadingState = document.getElementById('leadsLoadingState');
    const emptyState = document.getElementById('leadsEmptyState');
    const errorState = document.getElementById('leadsErrorState');
    const paginationBar = document.getElementById('leadsPaginationBar');

    if (loadingState) loadingState.classList.remove('hidden');
    if (emptyState) emptyState.classList.add('hidden');
    if (errorState) errorState.classList.add('hidden');
    if (tbody) tbody.innerHTML = '';

    const params = new URLSearchParams({
      page: state.page,
      page_size: state.pageSize,
      sort_by: state.sortBy,
      sort_order: state.sortOrder,
    });

    if (state.queueTab === 'interested') {
      params.append('status', 'Interested');
      params.append('needs_manual_followup', 'true');
      if (state.sortBy === 'created_at') {
        params.set('sort_by', 'last_replied_at');
        params.set('sort_order', 'desc');
      }
    } else {
      if (state.status) params.append('status', state.status);
    }

    if (state.search.trim()) params.append('search', state.search.trim());
    if (state.optInStatus) params.append('opt_in_status', state.optInStatus);
    if (state.followupPaused !== '') params.append('follow_up_paused', state.followupPaused);

    try {
      const response = await API.get(`/api/leads?${params.toString()}`);
      if (!response || !response.ok) {
        throw new Error(`API returned HTTP ${response ? response.status : 'error'}`);
      }

      const data = await response.json();
      state.items = data.items || [];
      state.total = data.total || 0;
      state.totalPages = data.total_pages || 1;

      if (loadingState) loadingState.classList.add('hidden');

      if (state.items.length === 0) {
        if (emptyState) emptyState.classList.remove('hidden');
        updatePaginationUI();
        updatePendingCallsBadge();
        return;
      }

      renderTableRows(state.items);
      updatePaginationUI();
      updatePendingCallsBadge();
    } catch (err) {
      console.error('Error loading leads:', err);
      if (loadingState) loadingState.classList.add('hidden');
      if (errorState) {
        errorState.classList.remove('hidden');
        const errorMsg = document.getElementById('leadsErrorMessage');
        if (errorMsg) errorMsg.textContent = err.message || 'Error retrieving leads';
      }
    }
  }

  // 2. Render table rows
  function renderTableRows(leads) {
    const tbody = document.getElementById('leadsTableBody');
    if (!tbody) return;

    tbody.innerHTML = leads.map(lead => {
      const isInterested = lead.status === 'Interested';
      const needsCall = Boolean(lead.needs_manual_followup);
      const phoneClean = escapeHtml(lead.phone_number);
      const telLink = `<a href="tel:${phoneClean}" class="phone-call-link" title="Click to call ${escapeHtml(lead.customer_name)}">${phoneClean}</a>`;

      let replyQuoteHtml = '';
      if (lead.last_reply_text) {
        const istTime = formatDateTimeIST(lead.last_replied_at);
        replyQuoteHtml = `
          <div class="lead-reply-quote" title="${escapeHtml(lead.last_reply_text)}">
            &ldquo;${escapeHtml(lead.last_reply_text)}&rdquo;
            <span class="reply-time">${istTime}</span>
          </div>
        `;
      }

      let callBadge = '';
      if (needsCall) {
        callBadge = `<span class="badge badge-call-needed" style="margin-left: 0.35rem;">Needs Call</span>`;
      }

      let markCallAction = '';
      if (needsCall) {
        markCallAction = `
          <button class="btn-action-call action-mark-called" data-id="${lead.id}" data-name="${escapeHtml(lead.customer_name)}" data-phone="${phoneClean}" data-reply="${escapeHtml(lead.last_reply_text || '')}" title="Mark as Called">
            Mark Called
          </button>
        `;
      }

      return `
        <tr data-lead-id="${lead.id}">
          <td><strong style="color: #64748b;">#${lead.id}</strong></td>
          <td><code>${escapeHtml(lead.serial_number || '—')}</code></td>
          <td>
            <a href="#" class="view-lead-link" data-id="${lead.id}" style="font-weight: 700; color: var(--primary); text-decoration: none;">
              ${escapeHtml(lead.customer_name)}
            </a>
            ${callBadge}
            ${replyQuoteHtml}
          </td>
          <td>${telLink}</td>
          <td>${getLeadStatusBadge(lead.status)}</td>
          <td>${getConsentBadge(lead.opt_in_status)}</td>
          <td>${getFollowupBadge(lead.follow_up_paused)}</td>
          <td style="font-size: 0.8rem; color: #64748b;">${formatDateTimeIST(lead.created_at).substring(0, 11)}</td>
          <td class="text-right">
            <div class="row-actions-group">
              ${markCallAction}
              <button class="btn-icon-sm action-view-lead" data-id="${lead.id}" title="View Complete Lead Details">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>
              </button>
              <button class="btn-icon-sm action-edit-lead" data-id="${lead.id}" title="Edit Lead Attributes">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
              </button>
              <button class="btn-icon-sm action-consent-lead" data-id="${lead.id}" title="Update WhatsApp Opt-In Consent">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>
              </button>
              <button class="btn-icon-sm action-toggle-pause" data-id="${lead.id}" data-paused="${lead.follow_up_paused}" title="${lead.follow_up_paused ? 'Resume Follow-ups' : 'Pause Follow-ups'}">
                ${lead.follow_up_paused
                  ? `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>`
                  : `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg>`
                }
              </button>
            </div>
          </td>
        </tr>
      `;
    }).join('');
  }

  // 3. Update pagination UI
  function updatePaginationUI() {
    const rangeText = document.getElementById('leadsRangeText');
    const totalCount = document.getElementById('leadsTotalCount');
    const pageBadge = document.getElementById('leadsCurrentPageBadge');
    const prevBtn = document.getElementById('leadsPrevBtn');
    const nextBtn = document.getElementById('leadsNextBtn');

    if (totalCount) totalCount.textContent = state.total.toLocaleString();

    if (state.total === 0) {
      if (rangeText) rangeText.textContent = '0-0';
      if (pageBadge) pageBadge.textContent = 'Page 0 of 0';
      if (prevBtn) prevBtn.disabled = true;
      if (nextBtn) nextBtn.disabled = true;
      return;
    }

    const start = (state.page - 1) * state.pageSize + 1;
    const end = Math.min(state.page * state.pageSize, state.total);
    if (rangeText) rangeText.textContent = `${start}-${end}`;
    if (pageBadge) pageBadge.textContent = `Page ${state.page} of ${Math.max(1, state.totalPages)}`;

    if (prevBtn) prevBtn.disabled = state.page <= 1;
    if (nextBtn) nextBtn.disabled = state.page >= state.totalPages;
  }

  // 4. Open Lead Details Modal with Follow-ups and Interaction History
  async function openLeadDetails(leadId) {
    const modal = document.getElementById('leadDetailModal');
    if (!modal) return;

    try {
      const response = await API.get(`/api/leads/${leadId}/detail`);
      if (!response || !response.ok) {
        showToast('Failed to load lead details', 'error');
        return;
      }

      const lead = await response.json();
      state.activeLeadDetail = lead;

      // Populate Header & Badges
      const title = document.getElementById('detailModalTitle');
      const subtitle = document.getElementById('detailModalSubtitle');
      if (title) title.textContent = lead.customer_name;
      if (subtitle) subtitle.textContent = `${lead.phone_number} • Serial: ${lead.serial_number || 'None'} • ID: #${lead.id}`;

      const statusBadge = document.getElementById('detailStatusBadge');
      const consentBadge = document.getElementById('detailConsentBadge');
      const followupBadge = document.getElementById('detailFollowupBadge');

      if (statusBadge) statusBadge.innerHTML = getLeadStatusBadge(lead.status);
      if (consentBadge) consentBadge.innerHTML = getConsentBadge(lead.opt_in_status);
      if (followupBadge) followupBadge.innerHTML = getFollowupBadge(lead.follow_up_paused);

      // Populate Tab 1: Profile & Consent Audit
      const cName = document.getElementById('detailCustomerName');
      const cPhone = document.getElementById('detailPhoneNumber');
      const cSerial = document.getElementById('detailSerialNumber');
      const cId = document.getElementById('detailLeadId');
      const cCreated = document.getElementById('detailCreatedAt');
      const cUpdated = document.getElementById('detailUpdatedAt');

      if (cName) cName.textContent = lead.customer_name;
      if (cPhone) cPhone.textContent = lead.phone_number;
      if (cSerial) cSerial.textContent = lead.serial_number || '—';
      if (cId) cId.textContent = `#${lead.id}`;
      if (cCreated) cCreated.textContent = formatDateTime(lead.created_at);
      if (cUpdated) cUpdated.textContent = formatDateTime(lead.updated_at);

      // Consent Audit Section
      const cConsentStatus = document.getElementById('detailConsentStatus');
      const cConsentSource = document.getElementById('detailConsentSource');
      const cOptInTime = document.getElementById('detailOptInTime');
      const cOptOutTime = document.getElementById('detailOptOutTime');

      if (cConsentStatus) cConsentStatus.textContent = lead.opt_in_status;
      if (cConsentSource) cConsentSource.textContent = lead.opt_in_source || '— (No source recorded)';
      if (cOptInTime) cOptInTime.textContent = formatDateTime(lead.opt_in_timestamp);
      if (cOptOutTime) cOptOutTime.textContent = formatDateTime(lead.opt_out_timestamp);

      // Inbound WhatsApp Reply & Call Status Section
      const cLastReply = document.getElementById('detailLastReplyText');
      const cLastRepliedAt = document.getElementById('detailLastRepliedAt');
      const cCallStatus = document.getElementById('detailCallQueueStatus');
      const cNotes = document.getElementById('detailFollowupNotes');
      const detailMarkCalledBtn = document.getElementById('detailMarkCalledBtn');

      if (cLastReply) cLastReply.textContent = lead.last_reply_text ? `"${lead.last_reply_text}"` : '—';
      if (cLastRepliedAt) cLastRepliedAt.textContent = formatDateTimeIST(lead.last_replied_at);
      if (cCallStatus) {
        if (lead.needs_manual_followup) {
          cCallStatus.innerHTML = '<span class="badge badge-call-needed">Action Required: Needs Phone Call</span>';
        } else if (lead.followed_up_at) {
          cCallStatus.innerHTML = `<span class="badge badge-opted-in">Followed up on ${formatDateTimeIST(lead.followed_up_at)}</span>`;
        } else {
          cCallStatus.innerHTML = '<span class="badge">No Call Pending</span>';
        }
      }
      if (cNotes) cNotes.textContent = lead.followup_notes || '—';

      if (detailMarkCalledBtn) {
        if (lead.needs_manual_followup) {
          detailMarkCalledBtn.classList.remove('hidden');
          detailMarkCalledBtn.onclick = () => {
            modal.classList.add('hidden');
            openMarkCalledModal(lead.id, lead.customer_name, lead.phone_number, lead.last_reply_text);
          };
        } else {
          detailMarkCalledBtn.classList.add('hidden');
        }
      }

      // Populate Tab 2: Follow-up Schedules
      const schedules = lead.follow_up_schedules || [];
      const schedCount = document.getElementById('tabSchedulesCount');
      if (schedCount) schedCount.textContent = schedules.length;

      const schedTbody = document.getElementById('detailSchedulesTableBody');
      const schedEmpty = document.getElementById('detailSchedulesEmpty');

      if (schedTbody) {
        if (schedules.length === 0) {
          schedTbody.innerHTML = '';
          if (schedEmpty) schedEmpty.classList.remove('hidden');
        } else {
          if (schedEmpty) schedEmpty.classList.add('hidden');
          schedTbody.innerHTML = schedules.map(s => `
            <tr>
              <td><strong>#${s.sequence_number}</strong></td>
              <td>${formatDateTime(s.scheduled_at)}</td>
              <td>Attempt ${s.attempt_number}</td>
              <td><span class="badge ${s.status === 'Sent' ? 'badge-opted-in' : (s.status === 'Cancelled' ? 'badge-opted-out' : 'badge-pending')}">${escapeHtml(s.status)}</span></td>
              <td>${escapeHtml(s.skip_reason || '—')}</td>
              <td>${formatDateTime(s.processed_at)}</td>
            </tr>
          `).join('');
        }
      }

      // Populate Tab 3: Customer Interaction History
      const messageLogs = lead.message_logs || [];
      const incomingMsgs = lead.incoming_messages || [];
      const histCount = document.getElementById('tabHistoryCount');
      if (histCount) histCount.textContent = messageLogs.length + incomingMsgs.length;

      const outTbody = document.getElementById('detailOutboundTableBody');
      const outEmpty = document.getElementById('detailOutboundEmpty');
      if (outTbody) {
        if (messageLogs.length === 0) {
          outTbody.innerHTML = '';
          if (outEmpty) outEmpty.classList.remove('hidden');
        } else {
          if (outEmpty) outEmpty.classList.add('hidden');
          outTbody.innerHTML = messageLogs.map(m => `
            <tr>
              <td><code>${escapeHtml(m.template_name || m.message_type)}</code></td>
              <td><span class="badge ${m.delivery_status === 'Delivered' || m.delivery_status === 'Read' ? 'badge-opted-in' : (m.delivery_status === 'Failed' ? 'badge-opted-out' : 'badge-pending')}">${escapeHtml(m.delivery_status)}</span></td>
              <td><code style="font-size: 0.75rem;">${escapeHtml(m.whatsapp_message_id || '—')}</code></td>
              <td>${formatDateTime(m.sent_at || m.created_at)}</td>
              <td>${formatDateTime(m.delivered_at)}</td>
              <td>${formatDateTime(m.read_at)}</td>
              <td>${formatDateTime(m.failed_at)}</td>
              <td style="color: #ef4444; font-size: 0.75rem;">${escapeHtml(m.error_details || '—')}</td>
            </tr>
          `).join('');
        }
      }

      const inTbody = document.getElementById('detailInboundTableBody');
      const inEmpty = document.getElementById('detailInboundEmpty');
      if (inTbody) {
        if (incomingMsgs.length === 0) {
          inTbody.innerHTML = '';
          if (inEmpty) inEmpty.classList.remove('hidden');
        } else {
          if (inEmpty) inEmpty.classList.add('hidden');
          inTbody.innerHTML = incomingMsgs.map(i => `
            <tr>
              <td>${formatDateTime(i.received_at)}</td>
              <td><strong>${escapeHtml(i.message_text || '—')}</strong></td>
              <td><span class="badge badge-replied">${escapeHtml(i.processing_status)}</span></td>
              <td><code style="font-size: 0.75rem;">${escapeHtml(i.whatsapp_message_id)}</code></td>
            </tr>
          `).join('');
        }
      }

      // Configure Footer Quick Action buttons
      const quickEditBtn = document.getElementById('detailQuickEditBtn');
      const quickConsentBtn = document.getElementById('detailQuickConsentBtn');
      const quickPauseBtn = document.getElementById('detailQuickPauseBtn');

      if (quickEditBtn) {
        quickEditBtn.onclick = () => {
          modal.classList.add('hidden');
          openEditModal(lead.id);
        };
      }

      if (quickConsentBtn) {
        quickConsentBtn.onclick = () => {
          modal.classList.add('hidden');
          openConsentModal(lead.id);
        };
      }

      if (quickPauseBtn) {
        quickPauseBtn.textContent = lead.follow_up_paused ? 'Resume Follow-ups' : 'Pause Follow-ups';
        quickPauseBtn.onclick = async () => {
          await togglePauseFollowup(lead.id, lead.follow_up_paused);
          modal.classList.add('hidden');
        };
      }

      // Activate first tab by default
      switchModalTab('tabProfile');
      modal.classList.remove('hidden');
    } catch (err) {
      console.error('Error opening lead detail modal:', err);
      showToast('Error displaying lead details', 'error');
    }
  }

  // 5. Modal Tab Switching
  function switchModalTab(tabId) {
    document.querySelectorAll('#leadDetailModal .modal-tab-btn').forEach(btn => {
      if (btn.getAttribute('data-tab') === tabId) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });

    document.querySelectorAll('#leadDetailModal .modal-tab-content').forEach(content => {
      if (content.id === tabId) {
        content.classList.add('active');
      } else {
        content.classList.remove('active');
      }
    });
  }

  // 6. Open Edit Modal
  async function openEditModal(leadId) {
    const modal = document.getElementById('leadEditModal');
    const form = document.getElementById('editLeadForm');
    const errorBox = document.getElementById('editLeadError');
    if (!modal || !form) return;

    if (errorBox) {
      errorBox.classList.add('hidden');
      errorBox.textContent = '';
    }

    try {
      const response = await API.get(`/api/leads/${leadId}`);
      if (!response || !response.ok) {
        showToast('Failed to retrieve lead for editing', 'error');
        return;
      }
      const lead = await response.json();

      document.getElementById('editLeadId').value = lead.id;
      document.getElementById('editCustomerName').value = lead.customer_name;
      document.getElementById('editPhoneNumber').value = lead.phone_number;
      document.getElementById('editSerialNumber').value = lead.serial_number || '';
      document.getElementById('editLeadStatus').value = lead.status;
      document.getElementById('editFollowupPaused').checked = Boolean(lead.follow_up_paused);

      modal.classList.remove('hidden');
    } catch (err) {
      console.error('Error opening edit modal:', err);
      showToast('Error opening edit modal', 'error');
    }
  }

  // 7. Save Edited Lead
  async function handleSaveEditLead(e) {
    e.preventDefault();
    const leadId = document.getElementById('editLeadId').value;
    const errorBox = document.getElementById('editLeadError');
    const saveBtn = document.getElementById('saveEditLeadBtn');

    if (errorBox) {
      errorBox.classList.add('hidden');
      errorBox.textContent = '';
    }

    const payload = {
      customer_name: document.getElementById('editCustomerName').value.trim(),
      phone_number: document.getElementById('editPhoneNumber').value.trim(),
      serial_number: document.getElementById('editSerialNumber').value.trim() || null,
      status: document.getElementById('editLeadStatus').value,
      follow_up_paused: document.getElementById('editFollowupPaused').checked,
    };

    if (!payload.customer_name) {
      if (errorBox) {
        errorBox.textContent = 'Customer name cannot be empty';
        errorBox.classList.remove('hidden');
      }
      return;
    }

    try {
      if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.textContent = 'Saving...';
      }

      const response = await API.patch(`/api/leads/${leadId}`, payload);
      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `Server returned HTTP ${response.status}`);
      }

      document.getElementById('leadEditModal').classList.add('hidden');
      showToast('Customer lead updated successfully');
      loadLeads();
    } catch (err) {
      console.error('Error saving lead edit:', err);
      if (errorBox) {
        errorBox.textContent = err.message || 'Failed to update lead';
        errorBox.classList.remove('hidden');
      }
    } finally {
      if (saveBtn) {
        saveBtn.disabled = false;
        saveBtn.textContent = 'Save Changes';
      }
    }
  }

  // 8. Open Consent Modal
  async function openConsentModal(leadId) {
    const modal = document.getElementById('leadConsentModal');
    const errorBox = document.getElementById('consentError');
    if (!modal) return;

    if (errorBox) {
      errorBox.classList.add('hidden');
      errorBox.textContent = '';
    }

    try {
      const response = await API.get(`/api/leads/${leadId}`);
      if (!response || !response.ok) {
        showToast('Failed to load lead consent profile', 'error');
        return;
      }
      const lead = await response.json();

      document.getElementById('consentLeadId').value = lead.id;
      document.getElementById('consentCustomerName').textContent = lead.customer_name;
      document.getElementById('consentCustomerPhone').textContent = lead.phone_number;

      const currentBadge = document.getElementById('consentCurrentBadge');
      if (currentBadge) currentBadge.innerHTML = getConsentBadge(lead.opt_in_status);

      const statusSelect = document.getElementById('consentStatusSelect');
      if (statusSelect) statusSelect.value = lead.opt_in_status;

      const sourceInput = document.getElementById('consentSourceInput');
      if (sourceInput) sourceInput.value = lead.opt_in_source || '';

      const quickSelect = document.getElementById('consentSourceQuickSelect');
      if (quickSelect) quickSelect.value = '';

      updateConsentSourceVisibility();
      modal.classList.remove('hidden');
    } catch (err) {
      console.error('Error opening consent modal:', err);
      showToast('Error opening consent modal', 'error');
    }
  }

  function updateConsentSourceVisibility() {
    const statusSelect = document.getElementById('consentStatusSelect');
    const sourceGroup = document.getElementById('consentSourceGroup');
    const sourceInput = document.getElementById('consentSourceInput');
    if (!statusSelect || !sourceGroup) return;

    if (statusSelect.value === 'OPTED_IN') {
      sourceGroup.classList.remove('hidden');
      if (sourceInput) sourceInput.required = true;
    } else {
      sourceGroup.classList.add('hidden');
      if (sourceInput) sourceInput.required = false;
    }
  }

  // 9. Save Consent Update
  async function handleSaveConsent(e) {
    e.preventDefault();
    const leadId = document.getElementById('consentLeadId').value;
    const errorBox = document.getElementById('consentError');
    const saveBtn = document.getElementById('saveConsentBtn');

    if (errorBox) {
      errorBox.classList.add('hidden');
      errorBox.textContent = '';
    }

    const optInStatus = document.getElementById('consentStatusSelect').value;
    const optInSource = document.getElementById('consentSourceInput').value.trim();

    if (optInStatus === 'OPTED_IN' && !optInSource) {
      if (errorBox) {
        errorBox.textContent = 'Verifiable consent source is mandatory when setting status to OPTED_IN.';
        errorBox.classList.remove('hidden');
      }
      return;
    }

    const payload = {
      opt_in_status: optInStatus,
      opt_in_source: optInSource || null,
    };

    try {
      if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.textContent = 'Updating...';
      }

      const response = await API.post(`/api/leads/${leadId}/consent`, payload);
      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `Server returned HTTP ${response.status}`);
      }

      document.getElementById('leadConsentModal').classList.add('hidden');
      showToast(`Consent updated to ${optInStatus}`);
      loadLeads();
    } catch (err) {
      console.error('Error updating consent:', err);
      if (errorBox) {
        errorBox.textContent = err.message || 'Failed to update consent';
        errorBox.classList.remove('hidden');
      }
    } finally {
      if (saveBtn) {
        saveBtn.disabled = false;
        saveBtn.textContent = 'Update Consent';
      }
    }
  }

  // 10. Open Create Lead Modal
  function openCreateModal() {
    const modal = document.getElementById('leadCreateModal');
    const form = document.getElementById('createLeadForm');
    const errorBox = document.getElementById('createLeadError');
    if (!modal || !form) return;

    form.reset();
    if (errorBox) {
      errorBox.classList.add('hidden');
      errorBox.textContent = '';
    }

    const consentGroup = document.getElementById('createConsentSourceGroup');
    if (consentGroup) consentGroup.classList.add('hidden');

    modal.classList.remove('hidden');
  }

  // 11. Save New Lead
  async function handleSaveCreateLead(e) {
    e.preventDefault();
    const errorBox = document.getElementById('createLeadError');
    const saveBtn = document.getElementById('saveCreateLeadBtn');

    if (errorBox) {
      errorBox.classList.add('hidden');
      errorBox.textContent = '';
    }

    const name = document.getElementById('createCustomerName').value.trim();
    const phone = document.getElementById('createPhoneNumber').value.trim();
    const serial = document.getElementById('createSerialNumber').value.trim() || null;
    const leadStatus = document.getElementById('createLeadStatus').value;
    const consentStatus = document.getElementById('createConsentStatus').value;
    const consentSource = document.getElementById('createConsentSource').value.trim();
    const pauseFollowups = document.getElementById('createFollowupPaused').checked;

    if (consentStatus === 'OPTED_IN' && !consentSource) {
      if (errorBox) {
        errorBox.textContent = 'Explicit verifiable consent source is mandatory when creating lead as OPTED_IN.';
        errorBox.classList.remove('hidden');
      }
      return;
    }

    const payload = {
      customer_name: name,
      phone_number: phone,
      serial_number: serial,
      status: leadStatus,
      opt_in_status: consentStatus,
      opt_in_source: consentSource || null,
      follow_up_paused: pauseFollowups,
    };

    try {
      if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.textContent = 'Creating...';
      }

      const response = await API.post('/api/leads', payload);
      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `Server returned HTTP ${response.status}`);
      }

      document.getElementById('leadCreateModal').classList.add('hidden');
      showToast('Lead created successfully');
      loadLeads();
    } catch (err) {
      console.error('Error creating lead:', err);
      if (errorBox) {
        errorBox.textContent = err.message || 'Failed to create lead';
        errorBox.classList.remove('hidden');
      }
    } finally {
      if (saveBtn) {
        saveBtn.disabled = false;
        saveBtn.textContent = 'Create Lead';
      }
    }
  }

  // 12. Toggle Pause/Resume Follow-ups
  async function togglePauseFollowup(leadId, currentPaused) {
    const isPaused = Boolean(currentPaused);
    const endpoint = isPaused ? `/api/leads/${leadId}/resume-followups` : `/api/leads/${leadId}/pause-followups`;
    const actionLabel = isPaused ? 'resumed' : 'paused';

    try {
      const response = await API.post(endpoint);
      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `Server returned HTTP ${response.status}`);
      }

      showToast(`Follow-ups ${actionLabel} successfully`);
      loadLeads();
    } catch (err) {
      console.error('Error toggling follow-up status:', err);
      showToast(`Failed to update follow-up state: ${err.message}`, 'error');
    }
  }

  // 13. Open & Process "Mark as Called" Modal
  function openMarkCalledModal(leadId, name, phone, replyText) {
    const modal = document.getElementById('markFollowedUpModal');
    const form = document.getElementById('markFollowedUpForm');
    const errorBox = document.getElementById('markFollowedUpError');
    if (!modal || !form) return;

    form.reset();
    if (errorBox) {
      errorBox.classList.add('hidden');
      errorBox.textContent = '';
    }

    const idInput = document.getElementById('markFollowedUpLeadId');
    const nameEl = document.getElementById('markFollowedUpName');
    const phoneEl = document.getElementById('markFollowedUpPhoneLink');
    const replyEl = document.getElementById('markFollowedUpReplyPreview');

    if (idInput) idInput.value = leadId;
    if (nameEl) nameEl.textContent = name || 'Customer';
    if (phoneEl) {
      phoneEl.textContent = phone || '';
      phoneEl.href = `tel:${phone || ''}`;
    }
    if (replyEl) {
      replyEl.textContent = replyText ? `"${replyText}"` : 'Customer replied on WhatsApp and requested a phone callback.';
    }

    modal.classList.remove('hidden');
  }

  async function handleSaveMarkFollowedUp(e) {
    e.preventDefault();
    const leadId = document.getElementById('markFollowedUpLeadId').value;
    const notes = document.getElementById('markFollowedUpNotesInput').value.trim();
    const errorBox = document.getElementById('markFollowedUpError');
    const saveBtn = document.getElementById('saveMarkFollowedUpBtn');

    if (errorBox) {
      errorBox.classList.add('hidden');
      errorBox.textContent = '';
    }

    try {
      if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.textContent = 'Recording call...';
      }

      const res = await API.post(`/api/leads/${leadId}/mark-followed-up`, {
        notes: notes || null,
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Server returned HTTP ${res.status}`);
      }

      document.getElementById('markFollowedUpModal').classList.add('hidden');
      showToast('Lead marked as called & cleared from action queue');
      loadLeads();
      updatePendingCallsBadge();
      if (typeof window.loadDashboardData === 'function') {
        window.loadDashboardData();
      }
    } catch (err) {
      console.error('Error marking lead as followed up:', err);
      if (errorBox) {
        errorBox.textContent = err.message || 'Failed to update lead follow-up status';
        errorBox.classList.remove('hidden');
      }
    } finally {
      if (saveBtn) {
        saveBtn.disabled = false;
        saveBtn.innerHTML = `
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>
          Confirm Call Completed
        `;
      }
    }
  }

  // 14. Queue Segmented Tabs switcher (Module Scoped)
  function switchQueueTab(tab) {
    state.queueTab = tab;
    state.page = 1;
    const tabAllLeadsBtn = document.getElementById('tabAllLeadsBtn');
    const tabInterestedCallsBtn = document.getElementById('tabInterestedCallsBtn');
    if (tabAllLeadsBtn) tabAllLeadsBtn.classList.toggle('active', tab === 'all');
    if (tabInterestedCallsBtn) tabInterestedCallsBtn.classList.toggle('active', tab === 'interested');
    loadLeads();
  }

  // 15. Event Delegation and Setup
  function setupEventListeners() {
    if (state.initialized) return;
    state.initialized = true;

    // Search input with debounce
    const searchInput = document.getElementById('leadSearchInput');
    const clearSearchBtn = document.getElementById('clearSearchBtn');

    if (searchInput) {
      searchInput.addEventListener('input', (e) => {
        const val = e.target.value;
        if (clearSearchBtn) {
          clearSearchBtn.classList.toggle('hidden', !val);
        }

        clearTimeout(state.debounceTimer);
        state.debounceTimer = setTimeout(() => {
          state.search = val;
          state.page = 1;
          loadLeads();
        }, 300);
      });
    }

    if (clearSearchBtn) {
      clearSearchBtn.addEventListener('click', () => {
        if (searchInput) searchInput.value = '';
        clearSearchBtn.classList.add('hidden');
        state.search = '';
        state.page = 1;
        loadLeads();
      });
    }

    // Filter Dropdowns
    const statusFilter = document.getElementById('leadStatusFilter');
    if (statusFilter) {
      statusFilter.addEventListener('change', (e) => {
        state.status = e.target.value;
        state.page = 1;
        loadLeads();
      });
    }

    const consentFilter = document.getElementById('leadConsentFilter');
    if (consentFilter) {
      consentFilter.addEventListener('change', (e) => {
        state.optInStatus = e.target.value;
        state.page = 1;
        loadLeads();
      });
    }

    const followupFilter = document.getElementById('leadFollowupFilter');
    if (followupFilter) {
      followupFilter.addEventListener('change', (e) => {
        state.followupPaused = e.target.value;
        state.page = 1;
        loadLeads();
      });
    }

    // Reset Filters
    const resetBtn = document.getElementById('resetLeadFiltersBtn');
    const emptyResetBtn = document.getElementById('emptyResetBtn');

    function resetAllFilters() {
      if (searchInput) searchInput.value = '';
      if (clearSearchBtn) clearSearchBtn.classList.add('hidden');
      if (statusFilter) statusFilter.value = '';
      if (consentFilter) consentFilter.value = '';
      if (followupFilter) followupFilter.value = '';

      state.search = '';
      state.status = '';
      state.optInStatus = '';
      state.followupPaused = '';
      state.page = 1;
      loadLeads();
    }

    if (resetBtn) resetBtn.addEventListener('click', resetAllFilters);
    if (emptyResetBtn) emptyResetBtn.addEventListener('click', resetAllFilters);

    // Refresh button
    const refreshBtn = document.getElementById('refreshLeadsBtn');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => {
        loadLeads();
        showToast('Leads directory refreshed');
      });
    }

    const retryBtn = document.getElementById('leadsRetryBtn');
    if (retryBtn) retryBtn.addEventListener('click', loadLeads);

    // Sortable headers
    document.querySelectorAll('#leadsTable thead th.sortable').forEach(th => {
      th.addEventListener('click', () => {
        const field = th.getAttribute('data-sort');
        if (state.sortBy === field) {
          state.sortOrder = state.sortOrder === 'asc' ? 'desc' : 'asc';
        } else {
          state.sortBy = field;
          state.sortOrder = 'desc';
        }

        document.querySelectorAll('#leadsTable thead th.sortable').forEach(el => {
          el.classList.remove('sorted-asc', 'sorted-desc');
        });
        th.classList.add(state.sortOrder === 'asc' ? 'sorted-asc' : 'sorted-desc');

        loadLeads();
      });
    });

    // Pagination buttons
    const prevBtn = document.getElementById('leadsPrevBtn');
    if (prevBtn) {
      prevBtn.addEventListener('click', () => {
        if (state.page > 1) {
          state.page--;
          loadLeads();
        }
      });
    }

    const nextBtn = document.getElementById('leadsNextBtn');
    if (nextBtn) {
      nextBtn.addEventListener('click', () => {
        if (state.page < state.totalPages) {
          state.page++;
          loadLeads();
        }
      });
    }

    const pageSizeSelect = document.getElementById('leadsPageSizeSelect');
    if (pageSizeSelect) {
      pageSizeSelect.addEventListener('change', (e) => {
        state.pageSize = parseInt(e.target.value, 10);
        state.page = 1;
        loadLeads();
      });
    }

    // Table Row Action Clicks (Event Delegation)
    const tableBody = document.getElementById('leadsTableBody');
    if (tableBody) {
      tableBody.addEventListener('click', (e) => {
        const viewLink = e.target.closest('.view-lead-link');
        if (viewLink) {
          e.preventDefault();
          const leadId = viewLink.getAttribute('data-id');
          openLeadDetails(leadId);
          return;
        }

        const viewBtn = e.target.closest('.action-view-lead');
        if (viewBtn) {
          e.preventDefault();
          const leadId = viewBtn.getAttribute('data-id');
          openLeadDetails(leadId);
          return;
        }

        const markCalledBtn = e.target.closest('.action-mark-called');
        if (markCalledBtn) {
          e.preventDefault();
          const leadId = markCalledBtn.getAttribute('data-id');
          const leadName = markCalledBtn.getAttribute('data-name');
          const leadPhone = markCalledBtn.getAttribute('data-phone');
          const leadReply = markCalledBtn.getAttribute('data-reply');
          openMarkCalledModal(leadId, leadName, leadPhone, leadReply);
          return;
        }

        const editBtn = e.target.closest('.action-edit-lead');
        if (editBtn) {
          e.preventDefault();
          const leadId = editBtn.getAttribute('data-id');
          openEditModal(leadId);
          return;
        }

        const consentBtn = e.target.closest('.action-consent-lead');
        if (consentBtn) {
          e.preventDefault();
          const leadId = consentBtn.getAttribute('data-id');
          openConsentModal(leadId);
          return;
        }

        const pauseBtn = e.target.closest('.action-toggle-pause');
        if (pauseBtn) {
          e.preventDefault();
          const leadId = pauseBtn.getAttribute('data-id');
          const isPaused = pauseBtn.getAttribute('data-paused') === 'true';
          togglePauseFollowup(leadId, isPaused);
          return;
        }
      });
    }

    // Modal Tabs
    document.querySelectorAll('#leadDetailModal .modal-tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const tab = btn.getAttribute('data-tab');
        switchModalTab(tab);
      });
    });

    // Close Modal buttons & backdrop click
    document.querySelectorAll('.modal-backdrop').forEach(backdrop => {
      backdrop.addEventListener('click', (e) => {
        if (e.target === backdrop) {
          backdrop.classList.add('hidden');
        }
      });
    });

    const closeDetailBtn = document.getElementById('closeDetailModalBtn');
    const closeDetailBottomBtn = document.getElementById('closeDetailModalBottomBtn');
    if (closeDetailBtn) closeDetailBtn.addEventListener('click', () => document.getElementById('leadDetailModal').classList.add('hidden'));
    if (closeDetailBottomBtn) closeDetailBottomBtn.addEventListener('click', () => document.getElementById('leadDetailModal').classList.add('hidden'));

    const closeEditBtn = document.getElementById('closeEditModalBtn');
    const cancelEditBtn = document.getElementById('cancelEditModalBtn');
    if (closeEditBtn) closeEditBtn.addEventListener('click', () => document.getElementById('leadEditModal').classList.add('hidden'));
    if (cancelEditBtn) cancelEditBtn.addEventListener('click', () => document.getElementById('leadEditModal').classList.add('hidden'));

    const closeConsentBtn = document.getElementById('closeConsentModalBtn');
    const cancelConsentBtn = document.getElementById('cancelConsentModalBtn');
    if (closeConsentBtn) closeConsentBtn.addEventListener('click', () => document.getElementById('leadConsentModal').classList.add('hidden'));
    if (cancelConsentBtn) cancelConsentBtn.addEventListener('click', () => document.getElementById('leadConsentModal').classList.add('hidden'));

    const closeCreateBtn = document.getElementById('closeCreateModalBtn');
    const cancelCreateBtn = document.getElementById('cancelCreateModalBtn');
    if (closeCreateBtn) closeCreateBtn.addEventListener('click', () => document.getElementById('leadCreateModal').classList.add('hidden'));
    if (cancelCreateBtn) cancelCreateBtn.addEventListener('click', () => document.getElementById('leadCreateModal').classList.add('hidden'));

    // Mark Followed Up Modal close buttons
    const closeMarkCalledBtn = document.getElementById('closeMarkFollowedUpBtn');
    const cancelMarkCalledBtn = document.getElementById('cancelMarkFollowedUpBtn');
    if (closeMarkCalledBtn) closeMarkCalledBtn.addEventListener('click', () => document.getElementById('markFollowedUpModal').classList.add('hidden'));
    if (cancelMarkCalledBtn) cancelMarkCalledBtn.addEventListener('click', () => document.getElementById('markFollowedUpModal').classList.add('hidden'));

    const markCalledForm = document.getElementById('markFollowedUpForm');
    if (markCalledForm) markCalledForm.addEventListener('submit', handleSaveMarkFollowedUp);

    // Queue Segmented Tabs
    const tabAllLeadsBtn = document.getElementById('tabAllLeadsBtn');
    const tabInterestedCallsBtn = document.getElementById('tabInterestedCallsBtn');

    if (tabAllLeadsBtn) tabAllLeadsBtn.addEventListener('click', () => switchQueueTab('all'));
    if (tabInterestedCallsBtn) tabInterestedCallsBtn.addEventListener('click', () => switchQueueTab('interested'));

    // Forms
    const editForm = document.getElementById('editLeadForm');
    if (editForm) editForm.addEventListener('submit', handleSaveEditLead);

    const consentForm = document.getElementById('consentForm');
    if (consentForm) consentForm.addEventListener('submit', handleSaveConsent);

    const consentStatusSelect = document.getElementById('consentStatusSelect');
    if (consentStatusSelect) consentStatusSelect.addEventListener('change', updateConsentSourceVisibility);

    const quickSelect = document.getElementById('consentSourceQuickSelect');
    if (quickSelect) {
      quickSelect.addEventListener('change', (e) => {
        const val = e.target.value;
        const input = document.getElementById('consentSourceInput');
        if (input && val && val !== 'custom') {
          input.value = val;
        }
      });
    }

    const openCreateBtn = document.getElementById('openCreateLeadModalBtn');
    if (openCreateBtn) openCreateBtn.addEventListener('click', openCreateModal);

    const createForm = document.getElementById('createLeadForm');
    if (createForm) createForm.addEventListener('submit', handleSaveCreateLead);

    const createConsentStatus = document.getElementById('createConsentStatus');
    if (createConsentStatus) {
      createConsentStatus.addEventListener('change', (e) => {
        const group = document.getElementById('createConsentSourceGroup');
        const input = document.getElementById('createConsentSource');
        if (group) {
          if (e.target.value === 'OPTED_IN') {
            group.classList.remove('hidden');
            if (input) input.required = true;
          } else {
            group.classList.add('hidden');
            if (input) input.required = false;
          }
        }
      });
    }

    // Escape key closes open modals
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        document.querySelectorAll('.modal-backdrop:not(.hidden)').forEach(modal => {
          modal.classList.add('hidden');
        });
      }
    });
  }

  // Public Interface
  window.LeadsManager = {
    init: function () {
      setupEventListeners();
      const urlParams = new URLSearchParams(window.location.search);
      if (urlParams.get('tab') === 'interested' || urlParams.get('queue') === 'interested') {
        switchQueueTab('interested');
      } else {
        loadLeads();
      }
    },
    loadLeads,
    openLeadDetails,
    openEditModal,
    openConsentModal,
    openCreateModal,
    togglePauseFollowup,
    openMarkCalledModal,
    switchQueueTab,
  };
})();
