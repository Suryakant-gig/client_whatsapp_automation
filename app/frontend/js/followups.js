/**
 * Follow-up Schedules Module Controller (Phase 9.6)
 * Handles viewing, filtering, rescheduling, cancelling, and manual execution
 * of automated customer follow-up sequences.
 */

(function () {
  'use strict';

  const state = {
    page: 1,
    pageSize: 20,
    statusFilter: '',
    leadIdFilter: '',
    items: [],
    total: 0,
    totalPages: 1,
    initialized: false,
    activeScheduleId: null,
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
      const d = new Date(isoString);
      if (isNaN(d.getTime())) return String(isoString);
      return d.toISOString().replace('T', ' ').substring(0, 19) + ' UTC';
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

  function getScheduleStatusBadge(status) {
    const s = escapeHtml(status || 'Scheduled');
    switch (status) {
      case 'Scheduled':
        return `<span class="badge badge-scheduled">Scheduled</span>`;
      case 'Approved':
        return `<span class="badge badge-approved">Approved</span>`;
      case 'Sent':
        return `<span class="badge badge-completed">Sent</span>`;
      case 'Skipped':
        return `<span class="badge badge-partially-failed">Skipped</span>`;
      case 'Cancelled':
        return `<span class="badge badge-rejected">Cancelled</span>`;
      case 'Failed':
        return `<span class="badge badge-failed">Failed</span>`;
      default:
        return `<span class="badge">${s}</span>`;
    }
  }

  async function loadFollowups() {
    const tbody = document.getElementById('followupsTableBody');
    const loadingState = document.getElementById('followupsLoadingState');
    const emptyState = document.getElementById('followupsEmptyState');
    const errorState = document.getElementById('followupsErrorState');
    const paginationBar = document.getElementById('followupsPaginationBar');

    if (loadingState) loadingState.classList.remove('hidden');
    if (emptyState) emptyState.classList.add('hidden');
    if (errorState) errorState.classList.add('hidden');
    if (tbody) tbody.innerHTML = '';

    try {
      const params = new URLSearchParams();
      params.set('page', state.page);
      params.set('page_size', state.pageSize);
      if (state.statusFilter) params.set('status', state.statusFilter);
      if (state.leadIdFilter) params.set('lead_id', state.leadIdFilter);

      const res = await API.get(`/api/followups?${params.toString()}`);
      if (!res || !res.ok) {
        throw new Error(`Failed to load schedules (HTTP ${res ? res.status : 'ERR'})`);
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
      renderFollowupsTable(state.items);
      renderPagination();
    } catch (err) {
      console.error('Error loading followups:', err);
      if (loadingState) loadingState.classList.add('hidden');
      if (errorState) {
        errorState.classList.remove('hidden');
        const errDesc = document.getElementById('followupsErrorText');
        if (errDesc) errDesc.textContent = err.message || 'Network error fetching follow-up schedules.';
      }
    }
  }

  function renderFollowupsTable(items) {
    const tbody = document.getElementById('followupsTableBody');
    if (!tbody) return;

    tbody.innerHTML = items.map(f => {
      const isPending = f.status === 'Scheduled' || f.status === 'Approved';

      return `
        <tr>
          <td><span class="table-id-badge">#${f.id}</span></td>
          <td>
            <strong>Lead #${f.lead_id}</strong>
          </td>
          <td>
            <span class="badge" style="background: #f1f5f9; color: #334155; font-weight: 600;">
              Seq #${f.sequence_number}
            </span>
          </td>
          <td><strong>${formatDateTime(f.scheduled_at)}</strong></td>
          <td>${getScheduleStatusBadge(f.status)}</td>
          <td>${f.attempt_number} attempt(s)</td>
          <td>${f.skip_reason ? `<span style="color: var(--danger); font-size: 0.75rem;">${escapeHtml(f.skip_reason)}</span>` : '<span class="text-muted">—</span>'}</td>
          <td><small class="text-muted">${formatDateTime(f.processed_at)}</small></td>
          <td class="text-right">
            <div class="row-actions-group">
              ${isPending ? `
                <button class="btn-table-action" data-action="reschedule" data-id="${f.id}" data-time="${f.scheduled_at}" title="Reschedule">
                  Reschedule
                </button>
                <button class="btn-table-action btn-action-danger" data-action="cancel" data-id="${f.id}" title="Cancel Schedule">
                  Cancel
                </button>
              ` : `
                <span class="text-muted" style="font-size: 0.75rem;">Completed</span>
              `}
            </div>
          </td>
        </tr>
      `;
    }).join('');

    // Attach row action listeners
    tbody.querySelectorAll('button[data-action]').forEach(btn => {
      btn.addEventListener('click', () => {
        const action = btn.getAttribute('data-action');
        const id = parseInt(btn.getAttribute('data-id'), 10);
        if (action === 'reschedule') {
          const currentTime = btn.getAttribute('data-time');
          openRescheduleModal(id, currentTime);
        } else if (action === 'cancel') {
          handleCancelSchedule(id);
        }
      });
    });
  }

  function renderPagination() {
    const rangeText = document.getElementById('followupsRangeText');
    const totalCount = document.getElementById('followupsTotalCount');
    const badge = document.getElementById('followupsCurrentPageBadge');
    const prevBtn = document.getElementById('followupsPrevBtn');
    const nextBtn = document.getElementById('followupsNextBtn');

    if (totalCount) totalCount.textContent = state.total.toLocaleString();

    const start = state.total === 0 ? 0 : (state.page - 1) * state.pageSize + 1;
    const end = Math.min(state.page * state.pageSize, state.total);
    if (rangeText) rangeText.textContent = `${start}-${end}`;

    if (badge) badge.textContent = `Page ${state.page} of ${Math.max(1, state.totalPages)}`;
    if (prevBtn) prevBtn.disabled = state.page <= 1;
    if (nextBtn) nextBtn.disabled = state.page >= state.totalPages;
  }

  function openRescheduleModal(scheduleId, currentTime) {
    state.activeScheduleId = scheduleId;
    const modal = document.getElementById('followupRescheduleModal');
    const idEl = document.getElementById('rescheduleScheduleId');
    const input = document.getElementById('rescheduleDateTimeInput');
    const errAlert = document.getElementById('rescheduleError');

    if (idEl) idEl.textContent = `#${scheduleId}`;
    if (errAlert) errAlert.classList.add('hidden');

    if (input) {
      // Format as local datetime-local string
      try {
        const d = currentTime ? new Date(currentTime) : new Date(Date.now() + 3600000);
        const pad = n => String(n).padStart(2, '0');
        const localIso = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
        input.value = localIso;
      } catch (_) {
        input.value = '';
      }
    }

    if (window.ModalManager) {
      window.ModalManager.open(modal);
    } else if (modal) {
      modal.classList.remove('hidden');
    }
  }

  async function handleRescheduleSubmit(e) {
    e.preventDefault();
    if (!state.activeScheduleId) return;

    const input = document.getElementById('rescheduleDateTimeInput');
    const errAlert = document.getElementById('rescheduleError');
    const submitBtn = document.getElementById('submitRescheduleBtn');

    const dtValue = input.value;
    if (!dtValue) {
      if (errAlert) {
        errAlert.textContent = 'Please choose a valid date and time.';
        errAlert.classList.remove('hidden');
      }
      return;
    }

    try {
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Updating...';
      }

      // Convert to UTC ISO string
      const utcDate = new Date(dtValue).toISOString();
      const res = await API.patch(`/api/followups/${state.activeScheduleId}`, {
        scheduled_at: utcDate,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to update schedule');
      }

      showToast(`Schedule #${state.activeScheduleId} rescheduled successfully!`, 'success');
      if (window.ModalManager) {
        window.ModalManager.close('#followupRescheduleModal');
      }
      loadFollowups();
    } catch (err) {
      if (errAlert) {
        errAlert.textContent = err.message || 'Error updating schedule.';
        errAlert.classList.remove('hidden');
      }
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Update Time';
      }
    }
  }

  async function handleCancelSchedule(scheduleId) {
    if (!confirm(`Are you sure you want to CANCEL follow-up schedule #${scheduleId}? Cancelled follow-ups will not be dispatched.`)) return;

    try {
      const res = await API.post(`/api/followups/${scheduleId}/cancel`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to cancel schedule');
      }
      showToast(`Schedule #${scheduleId} cancelled.`, 'success');
      loadFollowups();
    } catch (err) {
      showToast(err.message || 'Error cancelling schedule', 'error');
    }
  }

  async function handleProcessDueNow() {
    if (!confirm('Evaluate all overdue schedules and trigger APScheduler follow-up dispatch immediately?')) return;

    const btn = document.getElementById('processDueSchedulesBtn');
    try {
      if (btn) {
        btn.disabled = true;
        btn.textContent = 'Processing...';
      }

      const res = await API.post('/api/followups/process-due');
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Dispatcher processing failed');
      }

      const data = await res.json();
      showToast(`Due follow-ups processed: ${data.sent_count} sent, ${data.skipped_count} skipped, ${data.failed_count} failed.`, 'success');
      loadFollowups();
    } catch (err) {
      showToast(err.message || 'Error processing due follow-ups', 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = 'Process Due Now';
      }
    }
  }

  function init() {
    if (state.initialized) {
      loadFollowups();
      return;
    }
    state.initialized = true;

    const refreshBtn = document.getElementById('refreshFollowupsBtn');
    if (refreshBtn) refreshBtn.addEventListener('click', loadFollowups);

    const processDueBtn = document.getElementById('processDueSchedulesBtn');
    if (processDueBtn) processDueBtn.addEventListener('click', handleProcessDueNow);

    const statusFilter = document.getElementById('followupStatusFilter');
    if (statusFilter) {
      statusFilter.addEventListener('change', () => {
        state.statusFilter = statusFilter.value;
        state.page = 1;
        loadFollowups();
      });
    }

    const leadIdInput = document.getElementById('followupLeadIdInput');
    if (leadIdInput) {
      leadIdInput.addEventListener('input', () => {
        state.leadIdFilter = leadIdInput.value.trim();
        state.page = 1;
        loadFollowups();
      });
    }

    const resetFiltersBtn = document.getElementById('resetFollowupFiltersBtn');
    if (resetFiltersBtn) {
      resetFiltersBtn.addEventListener('click', () => {
        if (statusFilter) statusFilter.value = '';
        if (leadIdInput) leadIdInput.value = '';
        state.statusFilter = '';
        state.leadIdFilter = '';
        state.page = 1;
        loadFollowups();
      });
    }

    const prevBtn = document.getElementById('followupsPrevBtn');
    if (prevBtn) {
      prevBtn.addEventListener('click', () => {
        if (state.page > 1) {
          state.page--;
          loadFollowups();
        }
      });
    }

    const nextBtn = document.getElementById('followupsNextBtn');
    if (nextBtn) {
      nextBtn.addEventListener('click', () => {
        if (state.page < state.totalPages) {
          state.page++;
          loadFollowups();
        }
      });
    }

    const pageSizeSelect = document.getElementById('followupsPageSizeSelect');
    if (pageSizeSelect) {
      pageSizeSelect.addEventListener('change', () => {
        state.pageSize = parseInt(pageSizeSelect.value, 10);
        state.page = 1;
        loadFollowups();
      });
    }

    const rescheduleForm = document.getElementById('followupRescheduleForm');
    if (rescheduleForm) rescheduleForm.addEventListener('submit', handleRescheduleSubmit);

    loadFollowups();
  }

  window.FollowupsManager = {
    init,
    loadFollowups,
  };
})();
