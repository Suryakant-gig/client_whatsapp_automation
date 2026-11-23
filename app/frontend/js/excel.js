/**
 * Excel & CSV Synchronization Module Controller (Phase 9.6)
 * Handles workbook synchronization, file upload preview, lead diff inspection,
 * confirmed batch import, and timestamped backup auditing.
 */

(function () {
  'use strict';

  const state = {
    backups: [],
    previewData: null,
    selectedFile: null,
    isSyncing: false,
    isImporting: false,
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

  function formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
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
    }, 4000);
  }

  // =========================================================================
  // 1. Workbook Synchronization (DB -> Excel)
  // =========================================================================

  async function syncWorkbook() {
    const syncBtn = document.getElementById('excelTriggerSyncBtn');
    const syncStatusText = document.getElementById('excelSyncStatusText');
    if (state.isSyncing) return;

    try {
      state.isSyncing = true;
      if (syncBtn) {
        syncBtn.disabled = true;
        syncBtn.textContent = 'Syncing...';
      }
      if (syncStatusText) {
        syncStatusText.textContent = 'Writing records to authorized workbook and generating safety backup...';
      }

      const res = await API.post('/api/excel/sync', {});
      if (!res || !res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Workbook synchronization failed.');
      }

      const data = await res.json();
      showToast('Excel workbook synchronized successfully! Safety backup created.');
      if (syncStatusText) {
        syncStatusText.textContent = `Last synchronized: ${formatDateTime(data.timestamp || new Date().toISOString())}`;
      }

      // Refresh backup listing
      await loadBackups();
    } catch (err) {
      console.error('Sync error:', err);
      showToast(err.message || 'Synchronization failed', 'error');
      if (syncStatusText) {
        syncStatusText.textContent = `Sync failed: ${err.message}`;
      }
    } finally {
      state.isSyncing = false;
      if (syncBtn) {
        syncBtn.disabled = false;
        syncBtn.textContent = 'Sync Database to Workbook';
      }
    }
  }

  // =========================================================================
  // 2. Backup Audit Listing
  // =========================================================================

  async function loadBackups() {
    const tbody = document.getElementById('excelBackupsTableBody');
    const pathEl = document.getElementById('excelWorkbookPath');
    const dirEl = document.getElementById('excelBackupDir');
    if (!tbody) return;

    try {
      const res = await API.get('/api/excel/backups');
      if (!res || !res.ok) {
        throw new Error('Failed to retrieve backup history');
      }

      const data = await res.json();
      state.backups = data.backups || [];

      if (pathEl) pathEl.textContent = data.workbook_path || 'data/leads.xlsx';
      if (dirEl) dirEl.textContent = data.backup_dir || 'data/backups';

      if (state.backups.length === 0) {
        tbody.innerHTML = `
          <tr>
            <td colspan="4" class="text-center text-muted" style="padding: 2rem;">
              No automated backups found yet. Synchronizing the workbook will generate timestamped backups automatically.
            </td>
          </tr>
        `;
        return;
      }

      tbody.innerHTML = state.backups.map(b => `
        <tr>
          <td>
            <strong>${escapeHtml(b.filename)}</strong>
          </td>
          <td>
            <code style="font-size: 0.75rem; background: #f8fafc; padding: 2px 6px; border-radius: 4px;">
              ${escapeHtml(b.path)}
            </code>
          </td>
          <td>${formatBytes(b.size_bytes)}</td>
          <td>${formatDateTime(b.created_at)}</td>
        </tr>
      `).join('');
    } catch (err) {
      console.error('Error loading backups:', err);
      tbody.innerHTML = `
        <tr>
          <td colspan="4" style="color: var(--danger); padding: 1.5rem; text-align: center;">
            Error loading backups: ${escapeHtml(err.message)}
          </td>
        </tr>
      `;
    }
  }

  function clearSelectedFile() {
    state.selectedFile = null;
    state.previewData = null;
    const fileLabel = document.getElementById('excelSelectedFileName');
    if (fileLabel) fileLabel.textContent = 'No file chosen';
    const previewContainer = document.getElementById('excelPreviewSection');
    if (previewContainer) previewContainer.classList.add('hidden');
    const fileInput = document.getElementById('excelFileInput');
    if (fileInput) fileInput.value = '';
    const errorEl = document.getElementById('excelPreviewError');
    if (errorEl) errorEl.classList.add('hidden');
  }

  // =========================================================================
  // 3. File Upload & Pre-Commit Preview
  // =========================================================================

  async function handleFileSelect(file) {
    if (!file) return;

    const lower = file.name.toLowerCase();
    if (!lower.endsWith('.xlsx') && !lower.endsWith('.csv')) {
      showToast('Please select a valid Excel (.xlsx) or CSV (.csv) workbook.', 'error');
      return;
    }

    state.selectedFile = file;
    const fileLabel = document.getElementById('excelSelectedFileName');
    if (fileLabel) {
      fileLabel.innerHTML = `
        <span class="file-selected-chip">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>
          <span>${escapeHtml(file.name)} (${formatBytes(file.size)})</span>
          <button type="button" class="file-chip-remove" id="excelClearFileBtn" title="Remove file">&times;</button>
        </span>
      `;
      const clearBtn = document.getElementById('excelClearFileBtn');
      if (clearBtn) {
        clearBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          clearSelectedFile();
        });
      }
    }

    // Auto-trigger preview
    await uploadAndPreview();
  }

  async function uploadAndPreview() {
    if (!state.selectedFile) {
      showToast('Please select a file to preview.', 'error');
      return;
    }

    const previewContainer = document.getElementById('excelPreviewSection');
    const previewBtn = document.getElementById('excelPreviewBtn');
    const loadingEl = document.getElementById('excelPreviewLoading');
    const errorEl = document.getElementById('excelPreviewError');

    try {
      if (previewBtn) previewBtn.disabled = true;
      if (loadingEl) loadingEl.classList.remove('hidden');
      if (errorEl) errorEl.classList.add('hidden');
      if (previewContainer) previewContainer.classList.add('hidden');

      const formData = new FormData();
      formData.append('file', state.selectedFile);

      const res = await API.post('/api/import/preview', formData);
      if (!res || !res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to generate workbook preview.');
      }

      const preview = await res.json();
      state.previewData = preview;

      renderPreview(preview);
      if (previewContainer) previewContainer.classList.remove('hidden');
    } catch (err) {
      console.error('Preview error:', err);
      if (errorEl) {
        errorEl.textContent = err.message || 'Error processing workbook.';
        errorEl.classList.remove('hidden');
      }
      showToast(err.message || 'Preview generation failed', 'error');
    } finally {
      if (previewBtn) previewBtn.disabled = false;
      if (loadingEl) loadingEl.classList.add('hidden');
    }
  }

  function renderPreview(preview) {
    // Populate Diff KPIs
    const totalEl = document.getElementById('previewTotalRows');
    const validEl = document.getElementById('previewValidRows');
    const newEl = document.getElementById('previewNewLeads');
    const existingEl = document.getElementById('previewExistingLeads');
    const duplicateEl = document.getElementById('previewDuplicateRows');
    const invalidEl = document.getElementById('previewInvalidRows');

    if (totalEl) totalEl.textContent = preview.total_rows;
    if (validEl) validEl.textContent = preview.valid_rows;
    if (newEl) newEl.textContent = preview.eligible_for_import;
    if (existingEl) existingEl.textContent = preview.existing_leads;
    if (duplicateEl) duplicateEl.textContent = preview.duplicate_rows;
    if (invalidEl) invalidEl.textContent = preview.invalid_rows;

    // Confirm button state
    const confirmBtn = document.getElementById('excelConfirmImportBtn');
    if (confirmBtn) {
      if (preview.eligible_for_import > 0) {
        confirmBtn.disabled = false;
        confirmBtn.textContent = `Confirm & Import ${preview.eligible_for_import} Eligible Leads`;
      } else {
        confirmBtn.disabled = true;
        confirmBtn.textContent = 'No Eligible Leads to Import';
      }
    }

    // Diagnostics / Errors Table
    const errorsContainer = document.getElementById('previewErrorsContainer');
    const errorsTbody = document.getElementById('previewErrorsTableBody');
    if (errorsContainer && errorsTbody) {
      if (preview.errors && preview.errors.length > 0) {
        errorsContainer.classList.remove('hidden');
        errorsTbody.innerHTML = preview.errors.map(err => `
          <tr>
            <td>Row ${err.row_number}</td>
            <td><strong>${escapeHtml(err.field)}</strong></td>
            <td><code>${escapeHtml(err.value || '<empty>')}</code></td>
            <td><span class="badge badge-failed">${escapeHtml(err.error_code)}</span></td>
            <td>${escapeHtml(err.message)}</td>
          </tr>
        `).join('');
      } else {
        errorsContainer.classList.add('hidden');
      }
    }

    // Eligible Leads Sample Table
    const eligibleTbody = document.getElementById('previewEligibleTableBody');
    if (eligibleTbody) {
      const records = preview.eligible_records || [];
      if (records.length === 0) {
        eligibleTbody.innerHTML = `
          <tr>
            <td colspan="4" class="text-center text-muted">No new eligible leads identified in this workbook.</td>
          </tr>
        `;
      } else {
        eligibleTbody.innerHTML = records.slice(0, 25).map(rec => `
          <tr>
            <td>Row ${rec.row_number}</td>
            <td>${escapeHtml(rec.serial_number || '—')}</td>
            <td><strong>${escapeHtml(rec.customer_name)}</strong></td>
            <td><code>${escapeHtml(rec.phone_number)}</code></td>
          </tr>
        `).join('');
      }
    }
  }

  // =========================================================================
  // 4. Confirm & Commit Import
  // =========================================================================

  async function confirmImport() {
    if (!state.previewData || !state.previewData.eligible_records || state.previewData.eligible_records.length === 0) {
      showToast('No eligible records available to import.', 'error');
      return;
    }

    if (state.isImporting) return;

    const confirmBtn = document.getElementById('excelConfirmImportBtn');
    try {
      state.isImporting = true;
      if (confirmBtn) {
        confirmBtn.disabled = true;
        confirmBtn.textContent = 'Importing leads...';
      }

      const payload = {
        records: state.previewData.eligible_records,
        file_name: state.selectedFile ? state.selectedFile.name : 'uploaded_file',
      };

      const res = await API.post('/api/import/confirm', payload);
      if (!res || !res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Confirmation failed.');
      }

      const result = await res.json();
      showToast(`Successfully committed ${result.imported_count} leads to the database!`);

      // Reset preview section
      state.previewData = null;
      state.selectedFile = null;
      const fileLabel = document.getElementById('excelSelectedFileName');
      if (fileLabel) fileLabel.textContent = 'No file chosen';
      const previewContainer = document.getElementById('excelPreviewSection');
      if (previewContainer) previewContainer.classList.add('hidden');
      const fileInput = document.getElementById('excelFileInput');
      if (fileInput) fileInput.value = '';

      // Reload backups
      await loadBackups();
    } catch (err) {
      console.error('Import confirmation error:', err);
      showToast(err.message || 'Import failed', 'error');
    } finally {
      state.isImporting = false;
      if (confirmBtn) {
        confirmBtn.disabled = false;
        confirmBtn.textContent = 'Confirm & Import';
      }
    }
  }

  // =========================================================================
  // 5. Module Initialization
  // =========================================================================

  function init() {
    if (state.initialized) {
      loadBackups();
      return;
    }

    // Trigger sync button
    const syncBtn = document.getElementById('excelTriggerSyncBtn');
    if (syncBtn) {
      syncBtn.addEventListener('click', syncWorkbook);
    }

    // File input selection
    const fileInput = document.getElementById('excelFileInput');
    if (fileInput) {
      fileInput.addEventListener('change', (e) => {
        if (e.target.files && e.target.files[0]) {
          handleFileSelect(e.target.files[0]);
        }
      });
    }

    // Drag and drop zone
    const dropZone = document.getElementById('excelDropZone');
    if (dropZone) {
      ['dragenter', 'dragover'].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
          e.preventDefault();
          e.stopPropagation();
          dropZone.classList.add('drag-over');
        });
      });

      ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
          e.preventDefault();
          e.stopPropagation();
          dropZone.classList.remove('drag-over');
        });
      });

      dropZone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        if (dt && dt.files && dt.files[0]) {
          handleFileSelect(dt.files[0]);
        }
      });
    }

    // Confirm import button
    const confirmBtn = document.getElementById('excelConfirmImportBtn');
    if (confirmBtn) {
      confirmBtn.addEventListener('click', confirmImport);
    }

    // Refresh backups button
    const refreshBackupsBtn = document.getElementById('excelRefreshBackupsBtn');
    if (refreshBackupsBtn) {
      refreshBackupsBtn.addEventListener('click', loadBackups);
    }

    // Fallback copy helper
    function fallbackCopy(text) {
      try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        showToast(`Copied "${text}" to clipboard!`);
      } catch {
        showToast('Failed to copy to clipboard', 'error');
      }
    }

    // Path copy buttons
    document.querySelectorAll('#excelContainer .btn-copy-code').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        const targetId = btn.getAttribute('data-copy-target');
        const targetEl = targetId ? document.getElementById(targetId) : null;
        if (targetEl) {
          const textToCopy = targetEl.textContent.trim();
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(textToCopy).then(() => {
              showToast(`Copied "${textToCopy}" to clipboard!`);
            }).catch(() => {
              fallbackCopy(textToCopy);
            });
          } else {
            fallbackCopy(textToCopy);
          }
        }
      });
    });

    state.initialized = true;
    loadBackups();
  }

  window.ExcelSyncManager = {
    init,
    syncWorkbook,
    loadBackups,
    handleFileSelect,
    confirmImport,
  };
})();
