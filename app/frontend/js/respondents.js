/**
 * WhatsApp Respondents and Manual Contact Controller
 * Manages customer respondents, manual classification, 24-hr customer service window tracking,
 * conversation timeline history, and immediate manual WhatsApp messaging.
 */

window.RespondentsManager = (() => {
  let activeClassification = '';
  let currentPage = 1;
  let currentSearch = '';
  let isInterestedMode = false;
  let activeRespondent = null;
  let approvedTemplates = [];

  // DOM Elements - Respondents Section
  const respondentsTableBody = document.getElementById('respondentsTableBody');
  const respondentsLoadingState = document.getElementById('respondentsLoadingState');
  const respondentsEmptyState = document.getElementById('respondentsEmptyState');
  const respondentsErrorState = document.getElementById('respondentsErrorState');
  const respondentsPaginationBar = document.getElementById('respondentsPaginationBar');
  const respondentsPaginationInfo = document.getElementById('respondentsPaginationInfo');
  const respondentsPrevBtn = document.getElementById('respondentsPrevBtn');
  const respondentsNextBtn = document.getElementById('respondentsNextBtn');
  const respondentsPageBadge = document.getElementById('respondentsPageBadge');
  const respondentsSearchInput = document.getElementById('respondentsSearchInput');
  const respondentsRefreshBtn = document.getElementById('respondentsRefreshBtn');

  // KPI count displays
  const countTotalRespondents = document.getElementById('countTotalRespondents');
  const countInterestedRespondents = document.getElementById('countInterestedRespondents');
  const countUnclassifiedRespondents = document.getElementById('countUnclassifiedRespondents');
  const countNotInterestedRespondents = document.getElementById('countNotInterestedRespondents');

  // DOM Elements - Dedicated Interested Section
  const interestedTableBody = document.getElementById('interestedTableBody');
  const interestedLoadingState = document.getElementById('interestedLoadingState');
  const interestedEmptyState = document.getElementById('interestedEmptyState');
  const interestedErrorState = document.getElementById('interestedErrorState');
  const interestedSearchInput = document.getElementById('interestedSearchInput');
  const interestedRefreshBtn = document.getElementById('interestedRefreshBtn');
  const interestedTotalBadge = document.getElementById('interestedTotalBadge');

  // Manual Contact Modal Elements
  const manualContactModal = document.getElementById('manualContactModal');
  const manualContactForm = document.getElementById('manualContactForm');
  const manualContactError = document.getElementById('manualContactError');
  const contactCustomerName = document.getElementById('contactCustomerName');
  const contactPhoneNumber = document.getElementById('contactPhoneNumber');
  const contactWindowNotice = document.getElementById('contactWindowNotice');
  const contactWindowNoticeText = document.getElementById('contactWindowNoticeText');
  const contactTemplateSelect = document.getElementById('contactTemplateSelect');
  const contactMessageText = document.getElementById('contactMessageText');
  const contactSubmitBtn = document.getElementById('contactSubmitBtn');

  // History Modal Elements
  const respondentHistoryModal = document.getElementById('respondentHistoryModal');
  const historyCustomerName = document.getElementById('historyCustomerName');
  const historyPhoneNumber = document.getElementById('historyPhoneNumber');
  const historyTimelineContainer = document.getElementById('historyTimelineContainer');

  // Notes Modal Elements
  const respondentNotesModal = document.getElementById('respondentNotesModal');
  const respondentNotesForm = document.getElementById('respondentNotesForm');
  const notesCustomerName = document.getElementById('notesCustomerName');
  const respondentNotesText = document.getElementById('respondentNotesText');

  function showToast(message, type = 'success') {
    const toast = document.getElementById('toastNotification');
    const toastIcon = document.getElementById('toastIcon');
    const toastMsg = document.getElementById('toastMessage');
    if (!toast || !toastMsg) return;

    toast.className = `toast toast-${type}`;
    if (toastIcon) {
      toastIcon.innerHTML = type === 'success'
        ? '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>'
        : '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>';
    }
    toastMsg.textContent = message;
    toast.classList.remove('hidden');
    setTimeout(() => toast.classList.add('hidden'), 4500);
  }

  function formatDateTime(isoString) {
    if (!isoString) return '--';
    try {
      const dt = new Date(isoString);
      return dt.toLocaleDateString([], {
        day: '2-digit',
        month: 'short',
        year: 'numeric',
      }) + ' ' + dt.toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return isoString;
    }
  }

  async function loadApprovedTemplates() {
    try {
      const res = await API.get('/api/templates?approval_status=APPROVED');
      if (res && res.ok) {
        const data = await res.json();
        const templates = Array.isArray(data) ? data : (data.items || []);
        approvedTemplates = templates.filter(t => (t.approval_status || '').toUpperCase() === 'APPROVED');
      }
    } catch (err) {
      console.warn('Could not load approved templates for contact modal:', err);
    }
  }

  async function fetchRespondents() {
    const tableBody = isInterestedMode ? interestedTableBody : respondentsTableBody;
    const loadingState = isInterestedMode ? interestedLoadingState : respondentsLoadingState;
    const emptyState = isInterestedMode ? interestedEmptyState : respondentsEmptyState;
    const errorState = isInterestedMode ? interestedErrorState : respondentsErrorState;

    if (!tableBody) return;

    if (loadingState) loadingState.classList.remove('hidden');
    if (emptyState) emptyState.classList.add('hidden');
    if (errorState) errorState.classList.add('hidden');
    tableBody.innerHTML = '';

    try {
      const classificationParam = isInterestedMode ? 'INTERESTED' : activeClassification;
      const params = new URLSearchParams({
        page: currentPage.toString(),
        page_size: '20',
      });
      if (classificationParam) params.append('classification', classificationParam);
      if (currentSearch) params.append('search', currentSearch);

      const res = await API.get(`/api/respondents?${params.toString()}`);
      if (!res || !res.ok) {
        throw new Error(`Failed to load respondents (HTTP ${res ? res.status : 'Error'})`);
      }

      const data = await res.json();
      const items = data.items || [];
      const total = data.total || 0;
      const counts = data.counts || {};

      // Update count KPIs
      if (countTotalRespondents) countTotalRespondents.textContent = (counts.TOTAL || 0).toLocaleString();
      if (countInterestedRespondents) countInterestedRespondents.textContent = (counts.INTERESTED || 0).toLocaleString();
      if (countUnclassifiedRespondents) countUnclassifiedRespondents.textContent = (counts.UNCLASSIFIED || 0).toLocaleString();
      if (countNotInterestedRespondents) countNotInterestedRespondents.textContent = (counts.NOT_INTERESTED || 0).toLocaleString();
      if (interestedTotalBadge) interestedTotalBadge.textContent = `${counts.INTERESTED || 0} Contacts`;

      if (loadingState) loadingState.classList.add('hidden');

      if (items.length === 0) {
        if (emptyState) emptyState.classList.remove('hidden');
        if (respondentsPaginationBar && !isInterestedMode) respondentsPaginationBar.classList.add('hidden');
        return;
      }

      if (isInterestedMode) {
        renderInterestedTable(items);
      } else {
        renderRespondentsTable(items);
        updatePagination(data);
      }
    } catch (err) {
      console.error('Error fetching respondents:', err);
      if (loadingState) loadingState.classList.add('hidden');
      if (errorState) errorState.classList.remove('hidden');
    }
  }

  function getClassificationBadge(classification) {
    switch (classification) {
      case 'INTERESTED':
        return '<span class="status-pill status-approved" style="background: #ECFDF5; color: #047857; border: 1px solid #A7F3D0; font-weight: 600;">INTERESTED</span>';
      case 'UNCLASSIFIED':
        return '<span class="status-pill status-pending" style="background: #FEF3C7; color: #B45309; border: 1px solid #FDE68A; font-weight: 600;">UNCLASSIFIED</span>';
      case 'NOT_INTERESTED':
        return '<span class="status-pill status-rejected" style="background: #F1F5F9; color: #64748B; border: 1px solid #CBD5E1; font-weight: 600;">NOT INTERESTED</span>';
      case 'OTHER':
        return '<span class="status-pill" style="background: #EFF6FF; color: #1D4ED8; border: 1px solid #BFDBFE; font-weight: 600;">OTHER</span>';
      default:
        return `<span class="status-pill">${classification}</span>`;
    }
  }

  function renderRespondentsTable(items) {
    if (!respondentsTableBody) return;
    respondentsTableBody.innerHTML = items.map(r => {
      const name = r.name || 'Anonymous Customer';
      const phone = r.phone_number;
      const windowBadge = r.within_24h_window
        ? '<span class="badge" style="background: #ECFDF5; color: #047857; font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 6px; border: 1px solid #A7F3D0;"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="display:inline; margin-right:3px; vertical-align:middle;"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>Within 24h</span>'
        : `<span class="badge" style="background: #F8FAFC; color: #64748B; font-size: 11px; padding: 3px 8px; border-radius: 6px; border: 1px solid #E2E8F0;">Outside 24h (${r.hours_since_last_reply}h)</span>`;

      const campaign = r.original_campaign_name || '<span style="color:#94A3B8;">Direct / Organic</span>';
      const notes = r.internal_notes ? `<span title="${escapeHtml(r.internal_notes)}" style="cursor:help; font-size:12px; color:#475569;">${escapeHtml(r.internal_notes.slice(0, 35))}${r.internal_notes.length > 35 ? '...' : ''}</span>` : '<span style="color:#CBD5E1; font-size:12px;">No notes</span>';

      return `
        <tr data-id="${r.id}">
          <td style="font-weight: 600; color: #0F172A;">
            <div style="font-size: 14px;">${escapeHtml(name)}</div>
            <div style="font-size: 12px; color: #64748B; font-family: monospace;">${escapeHtml(phone)}</div>
          </td>
          <td>
            <select class="form-select classification-select" data-id="${r.id}" style="font-size: 12px; height: 30px; padding: 2px 24px 2px 8px; font-weight: 600; border-radius: 6px; background-color: #FFFFFF;">
              <option value="UNCLASSIFIED" ${r.classification === 'UNCLASSIFIED' ? 'selected' : ''}>UNCLASSIFIED</option>
              <option value="INTERESTED" ${r.classification === 'INTERESTED' ? 'selected' : ''}>INTERESTED</option>
              <option value="NOT_INTERESTED" ${r.classification === 'NOT_INTERESTED' ? 'selected' : ''}>NOT INTERESTED</option>
              <option value="OTHER" ${r.classification === 'OTHER' ? 'selected' : ''}>OTHER</option>
            </select>
          </td>
          <td>${windowBadge}</td>
          <td style="font-size: 13px; color: #334155;">${campaign}</td>
          <td style="font-size: 12px; color: #64748B;">${formatDateTime(r.last_reply_at)}</td>
          <td>${notes}</td>
          <td class="text-right" style="white-space: nowrap;">
            <button type="button" class="btn-action-primary btn-contact-respondent" data-id="${r.id}" style="height: 30px; padding: 0 10px; font-size: 12px; margin-right: 4px;">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right: 4px;"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg>
              Message
            </button>
            <button type="button" class="btn-action-outline btn-view-history" data-id="${r.id}" style="height: 30px; padding: 0 8px; font-size: 12px; margin-right: 4px;" title="View Message History">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"></path><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path></svg>
            </button>
            <button type="button" class="btn-action-outline btn-edit-notes" data-id="${r.id}" style="height: 30px; padding: 0 8px; font-size: 12px;" title="Edit Internal Notes">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="8" y1="6" x2="21" y2="6"></line><line x1="8" y1="12" x2="21" y2="12"></line><line x1="8" y1="18" x2="21" y2="18"></line><line x1="3" y1="6" x2="3.01" y2="6"></line><line x1="3" y1="12" x2="3.01" y2="12"></line><line x1="3" y1="18" x2="3.01" y2="18"></line></svg>
            </button>
          </td>
        </tr>
      `;
    }).join('');

    bindTableEvents(respondentsTableBody);
  }

  function renderInterestedTable(items) {
    if (!interestedTableBody) return;
    interestedTableBody.innerHTML = items.map(r => {
      const name = r.name || 'Anonymous Customer';
      const phone = r.phone_number;
      const windowBadge = r.within_24h_window
        ? '<span class="badge" style="background: #ECFDF5; color: #047857; font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 6px; border: 1px solid #A7F3D0;">Within 24h</span>'
        : `<span class="badge" style="background: #F8FAFC; color: #64748B; font-size: 11px; padding: 3px 8px; border-radius: 6px; border: 1px solid #E2E8F0;">Outside 24h</span>`;

      const campaign = r.original_campaign_name || '<span style="color:#94A3B8;">Direct / Organic</span>';
      const notes = r.internal_notes ? `<span title="${escapeHtml(r.internal_notes)}" style="cursor:help; font-size:12px; color:#475569;">${escapeHtml(r.internal_notes.slice(0, 40))}${r.internal_notes.length > 40 ? '...' : ''}</span>` : '<span style="color:#CBD5E1; font-size:12px;">No notes</span>';

      return `
        <tr data-id="${r.id}">
          <td style="font-weight: 600; color: #0F172A;">
            <div style="font-size: 14px;">${escapeHtml(name)}</div>
            <div style="font-size: 12px; color: #64748B; font-family: monospace;">${escapeHtml(phone)}</div>
          </td>
          <td>
            <select class="form-select classification-select" data-id="${r.id}" style="font-size: 12px; height: 30px; padding: 2px 24px 2px 8px; font-weight: 600; border-radius: 6px; background-color: #ECFDF5; color: #047857; border: 1px solid #A7F3D0;">
              <option value="INTERESTED" selected>INTERESTED</option>
              <option value="UNCLASSIFIED">UNCLASSIFIED</option>
              <option value="NOT_INTERESTED">NOT INTERESTED</option>
              <option value="OTHER">OTHER</option>
            </select>
          </td>
          <td>${windowBadge}</td>
          <td style="font-size: 13px; color: #334155;">${campaign}</td>
          <td style="font-size: 12px; color: #64748B;">${formatDateTime(r.last_reply_at)}</td>
          <td>${notes}</td>
          <td class="text-right" style="white-space: nowrap;">
            <a href="tel:${escapeHtml(phone)}" class="btn-action-outline" style="height: 30px; padding: 0 10px; font-size: 12px; margin-right: 4px; display: inline-flex; align-items: center; text-decoration: none; color: #047857; border-color: #A7F3D0; background: #ECFDF5;">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right: 4px;"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"></path></svg>
              Call
            </a>
            <button type="button" class="btn-action-primary btn-contact-respondent" data-id="${r.id}" style="height: 30px; padding: 0 10px; font-size: 12px; margin-right: 4px;">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right: 4px;"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg>
              WhatsApp
            </button>
            <button type="button" class="btn-action-outline btn-view-history" data-id="${r.id}" style="height: 30px; padding: 0 8px; font-size: 12px; margin-right: 4px;" title="View Message History">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"></path><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path></svg>
            </button>
            <button type="button" class="btn-action-outline btn-edit-notes" data-id="${r.id}" style="height: 30px; padding: 0 8px; font-size: 12px;" title="Edit Internal Notes">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="8" y1="6" x2="21" y2="6"></line><line x1="8" y1="12" x2="21" y2="12"></line><line x1="8" y1="18" x2="21" y2="18"></line><line x1="3" y1="6" x2="3.01" y2="6"></line><line x1="3" y1="12" x2="3.01" y2="12"></line><line x1="3" y1="18" x2="3.01" y2="18"></line></svg>
            </button>
          </td>
        </tr>
      `;
    }).join('');

    bindTableEvents(interestedTableBody);
  }

  function bindTableEvents(container) {
    // Classification dropdown change
    container.querySelectorAll('.classification-select').forEach(sel => {
      sel.addEventListener('change', async (e) => {
        const respondentId = e.target.getAttribute('data-id');
        const newClass = e.target.value;
        try {
          const res = await API.patch(`/api/respondents/${respondentId}/classification`, {
            classification: newClass,
          });
          if (res && res.ok) {
            showToast(`Classification updated to ${newClass}`);
            fetchRespondents();
          } else {
            const errData = await res.json();
            alert(`Failed to update: ${errData.detail || 'Error'}`);
            fetchRespondents();
          }
        } catch (err) {
          console.error('Error updating classification:', err);
          fetchRespondents();
        }
      });
    });

    // Contact button click
    container.querySelectorAll('.btn-contact-respondent').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const respondentId = btn.getAttribute('data-id');
        openManualContactModal(respondentId);
      });
    });

    // View history button click
    container.querySelectorAll('.btn-view-history').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const respondentId = btn.getAttribute('data-id');
        openHistoryModal(respondentId);
      });
    });

    // Edit notes button click
    container.querySelectorAll('.btn-edit-notes').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const respondentId = btn.getAttribute('data-id');
        openNotesModal(respondentId);
      });
    });
  }

  function updatePagination(data) {
    if (!respondentsPaginationBar) return;
    const total = data.total || 0;
    const pages = data.pages || 1;

    if (total === 0) {
      respondentsPaginationBar.classList.add('hidden');
      return;
    }
    respondentsPaginationBar.classList.remove('hidden');

    if (respondentsPaginationInfo) {
      const start = (currentPage - 1) * 20 + 1;
      const end = Math.min(currentPage * 20, total);
      respondentsPaginationInfo.innerHTML = `Showing <strong>${start}-${end}</strong> of <strong>${total}</strong> respondents`;
    }

    if (respondentsPageBadge) respondentsPageBadge.textContent = `Page ${currentPage} of ${pages}`;
    if (respondentsPrevBtn) respondentsPrevBtn.disabled = currentPage <= 1;
    if (respondentsNextBtn) respondentsNextBtn.disabled = currentPage >= pages;
  }

  async function openManualContactModal(respondentId) {
    if (!manualContactModal) return;
    if (manualContactError) manualContactError.classList.add('hidden');

    try {
      const res = await API.get(`/api/respondents/${respondentId}`);
      if (!res || !res.ok) throw new Error('Failed to load respondent');
      const data = await res.json();
      activeRespondent = data.respondent;

      if (contactCustomerName) contactCustomerName.textContent = activeRespondent.name || 'Anonymous Customer';
      if (contactPhoneNumber) contactPhoneNumber.textContent = activeRespondent.phone_number;

      // Populate template dropdown
      if (contactTemplateSelect) {
        contactTemplateSelect.innerHTML = '<option value="">-- Custom Text (Within 24h Window) --</option>' +
          approvedTemplates.map(t => `<option value="${escapeHtml(t.template_name)}">${escapeHtml(t.template_name)} (${t.language})</option>`).join('');
      }

      // Check 24-hr window notice
      if (contactWindowNotice && contactWindowNoticeText) {
        if (activeRespondent.within_24h_window) {
          contactWindowNotice.className = 'form-alert success';
          contactWindowNotice.style.display = 'block';
          contactWindowNoticeText.innerHTML = `<strong>Within 24h Window:</strong> Customer replied ${activeRespondent.hours_since_last_reply} hours ago. Freeform custom messages or approved templates are permitted.`;
          if (contactMessageText) contactMessageText.disabled = false;
        } else {
          contactWindowNotice.className = 'form-alert warning';
          contactWindowNotice.style.display = 'block';
          contactWindowNoticeText.innerHTML = `<strong>Outside 24h Window:</strong> Customer replied ${activeRespondent.hours_since_last_reply} hours ago. Meta requires an approved template to message this customer.`;
          if (contactTemplateSelect && approvedTemplates.length > 0) {
            contactTemplateSelect.value = approvedTemplates[0].template_name;
          }
        }
      }

      manualContactModal.classList.remove('hidden');
    } catch (err) {
      alert('Error opening contact modal: ' + err.message);
    }
  }

  async function openHistoryModal(respondentId) {
    if (!respondentHistoryModal) return;
    if (historyTimelineContainer) historyTimelineContainer.innerHTML = '<div class="spinner"></div>';

    try {
      const res = await API.get(`/api/respondents/${respondentId}`);
      if (!res || !res.ok) throw new Error('Failed to load history');
      const data = await res.json();
      const r = data.respondent;
      const history = data.conversation_history || [];

      if (historyCustomerName) historyCustomerName.textContent = r.name || 'Customer';
      if (historyPhoneNumber) historyPhoneNumber.textContent = r.phone_number;

      if (history.length === 0) {
        historyTimelineContainer.innerHTML = '<div style="padding: 32px; text-align: center; color: #64748B;">No message history recorded yet.</div>';
      } else {
        historyTimelineContainer.innerHTML = history.map(item => {
          const isInbound = item.direction === 'inbound';
          const bubbleStyle = isInbound
            ? 'background: #F1F5F9; color: #0F172A; border-radius: 12px 12px 12px 2px; align-self: flex-start; max-width: 80%;'
            : 'background: #047857; color: #FFFFFF; border-radius: 12px 12px 2px 12px; align-self: flex-end; max-width: 80%;';

          const statusBadge = isInbound
            ? '<span style="font-size: 10px; color: #64748B;">Received</span>'
            : `<span style="font-size: 10px; color: #D1FAE5; opacity: 0.9;">${item.delivery_status}</span>`;

          return `
            <div style="display: flex; flex-direction: column; margin-bottom: 12px;">
              <div style="${bubbleStyle} padding: 10px 14px; box-shadow: 0 1px 2px rgba(0,0,0,0.05);">
                <div style="font-size: 13px; line-height: 1.4; word-break: break-word;">${escapeHtml(item.message_text || '')}</div>
                <div style="display: flex; justify-content: flex-end; gap: 8px; margin-top: 4px; align-items: center;">
                  <span style="font-size: 10px; opacity: 0.7;">${formatDateTime(item.timestamp)}</span>
                  ${statusBadge}
                </div>
              </div>
            </div>
          `;
        }).join('');
      }

      respondentHistoryModal.classList.remove('hidden');
    } catch (err) {
      alert('Error loading history: ' + err.message);
    }
  }

  async function openNotesModal(respondentId) {
    if (!respondentNotesModal) return;
    try {
      const res = await API.get(`/api/respondents/${respondentId}`);
      if (!res || !res.ok) throw new Error('Failed to load respondent');
      const data = await res.json();
      activeRespondent = data.respondent;

      if (notesCustomerName) notesCustomerName.textContent = activeRespondent.name || activeRespondent.phone_number;
      if (respondentNotesText) respondentNotesText.value = activeRespondent.internal_notes || '';

      respondentNotesModal.classList.remove('hidden');
    } catch (err) {
      alert('Error loading notes: ' + err.message);
    }
  }

  function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/[&<>"']/g, (m) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#039;',
    }[m]));
  }

  function init(filter = 'all') {
    isInterestedMode = false;
    activeClassification = filter === 'all' ? '' : filter.toUpperCase();
    currentPage = 1;
    currentSearch = '';
    if (respondentsSearchInput) respondentsSearchInput.value = '';

    // Set active tab styling
    document.querySelectorAll('.respondents-filter-tab').forEach(tab => {
      const f = tab.getAttribute('data-filter') || 'all';
      if (f.toLowerCase() === filter.toLowerCase()) {
        tab.classList.add('active');
      } else {
        tab.classList.remove('active');
      }
    });

    loadApprovedTemplates();
    fetchRespondents();
  }

  function initInterested() {
    isInterestedMode = true;
    currentPage = 1;
    currentSearch = '';
    if (interestedSearchInput) interestedSearchInput.value = '';

    loadApprovedTemplates();
    fetchRespondents();
  }

  // Event Listeners Setup
  function setupEventListeners() {
    // Classification Filter Tabs
    document.querySelectorAll('.respondents-filter-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        const f = tab.getAttribute('data-filter') || 'all';
        init(f);
      });
    });

    // Search input (debounce)
    let searchTimeout = null;
    if (respondentsSearchInput) {
      respondentsSearchInput.addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
          currentSearch = e.target.value.trim();
          currentPage = 1;
          fetchRespondents();
        }, 300);
      });
    }

    if (interestedSearchInput) {
      interestedSearchInput.addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
          currentSearch = e.target.value.trim();
          currentPage = 1;
          fetchRespondents();
        }, 300);
      });
    }

    if (respondentsRefreshBtn) {
      respondentsRefreshBtn.addEventListener('click', () => fetchRespondents());
    }

    if (interestedRefreshBtn) {
      interestedRefreshBtn.addEventListener('click', () => fetchRespondents());
    }

    // Pagination
    if (respondentsPrevBtn) {
      respondentsPrevBtn.addEventListener('click', () => {
        if (currentPage > 1) {
          currentPage--;
          fetchRespondents();
        }
      });
    }

    if (respondentsNextBtn) {
      respondentsNextBtn.addEventListener('click', () => {
        currentPage++;
        fetchRespondents();
      });
    }

    // Manual Contact Form Submission
    if (manualContactForm) {
      manualContactForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (!activeRespondent) return;

        if (contactSubmitBtn) {
          contactSubmitBtn.disabled = true;
          contactSubmitBtn.innerHTML = '<div class="spinner-sm" style="display:inline-block; margin-right:6px;"></div> Sending...';
        }
        if (manualContactError) manualContactError.classList.add('hidden');

        try {
          const templateName = contactTemplateSelect ? contactTemplateSelect.value.trim() : '';
          const messageText = contactMessageText ? contactMessageText.value.trim() : '';

          const payload = {
            template_name: templateName || null,
            message_text: messageText || null,
            template_language: 'en',
          };

          const res = await API.post(`/api/respondents/${activeRespondent.id}/contact`, payload);
          if (res && res.ok) {
            const data = await res.json();
            showToast(`WhatsApp message dispatched immediately (${data.delivery_status})`);
            manualContactModal.classList.add('hidden');
            fetchRespondents();
          } else {
            const errData = await res.json();
            if (manualContactError) {
              manualContactError.textContent = errData.detail || 'Failed to dispatch message';
              manualContactError.classList.remove('hidden');
            }
          }
        } catch (err) {
          if (manualContactError) {
            manualContactError.textContent = err.message || 'Error communicating with server';
            manualContactError.classList.remove('hidden');
          }
        } finally {
          if (contactSubmitBtn) {
            contactSubmitBtn.disabled = false;
            contactSubmitBtn.innerHTML = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:6px;"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg> Send Message Now';
          }
        }
      });
    }

    // Notes Form Submission
    if (respondentNotesForm) {
      respondentNotesForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (!activeRespondent) return;

        const notes = respondentNotesText ? respondentNotesText.value.trim() : '';
        try {
          const res = await API.patch(`/api/respondents/${activeRespondent.id}/notes`, {
            internal_notes: notes || null,
          });
          if (res && res.ok) {
            showToast('Internal notes updated');
            respondentNotesModal.classList.add('hidden');
            fetchRespondents();
          } else {
            const errData = await res.json();
            alert('Failed to save notes: ' + (errData.detail || 'Error'));
          }
        } catch (err) {
          alert('Error saving notes: ' + err.message);
        }
      });
    }
  }

  document.addEventListener('DOMContentLoaded', setupEventListeners);

  return {
    init,
    initInterested,
    fetchRespondents,
  };
})();
