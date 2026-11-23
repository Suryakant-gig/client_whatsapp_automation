/**
 * Application & Security Settings Module Controller (Phase 9.6)
 * Handles administrator credential management (password change), session review,
 * and system integration health monitoring.
 */

(function () {
  'use strict';

  const state = {
    user: null,
    isSubmitting: false,
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
  // 1. Load Current User Profile & System Status
  // =========================================================================

  async function loadSettingsData() {
    try {
      const [authRes, overviewRes] = await Promise.all([
        API.get('/api/auth/me'),
        API.get('/api/dashboard/overview'),
      ]);

      if (authRes && authRes.ok) {
        state.user = await authRes.json();
        renderUserProfile(state.user);
      }

      if (overviewRes && overviewRes.ok) {
        const overview = await overviewRes.json();
        renderSystemHealth(overview);
      }
    } catch (err) {
      console.error('Error loading settings data:', err);
    }
  }

  function renderUserProfile(user) {
    const nameEl = document.getElementById('settingsUsername');
    const roleEl = document.getElementById('settingsRoleBadge');
    const idEl = document.getElementById('settingsUserId');
    const roleTextEl = document.getElementById('settingsUserRoleText');

    if (nameEl) nameEl.textContent = user.username;
    if (roleEl) roleEl.textContent = (user.role || 'ADMIN').toUpperCase();
    if (idEl) idEl.textContent = user.id;
    if (roleTextEl) roleTextEl.textContent = (user.role === 'admin' ? 'Active Administrator' : 'Staff Account');
  }

  function renderSystemHealth(data) {
    const schedulerTag = document.getElementById('settingsSchedulerTag');
    const whatsappTag = document.getElementById('settingsWhatsAppTag');

    if (schedulerTag) {
      if (data.scheduler_enabled) {
        schedulerTag.textContent = 'ACTIVE (Running)';
        schedulerTag.className = 'health-status-tag active';
      } else {
        schedulerTag.textContent = 'DISABLED';
        schedulerTag.className = 'health-status-tag inactive';
      }
    }

    if (whatsappTag) {
      if (data.whatsapp_enabled) {
        whatsappTag.textContent = 'LIVE (Cloud API Connected)';
        whatsappTag.className = 'health-status-tag active';
      } else {
        whatsappTag.textContent = 'OFFLINE (MOCK Dispatcher)';
        whatsappTag.className = 'health-status-tag inactive';
      }
    }

    const whatsappSubtitle = document.getElementById('settingsWhatsAppSubtitle') || document.getElementById('diagWhatsappSubtitle');
    if (whatsappSubtitle) {
      if (data.whatsapp_enabled) {
        whatsappSubtitle.textContent = 'Connected to Meta WhatsApp Cloud API for live message dispatch.';
      } else {
        whatsappSubtitle.textContent = 'Mock dispatcher mode ensures safe offline development until credentials are set.';
      }
    }

    const diagWhatsappStatus = document.getElementById('diagWhatsappStatus');
    if (diagWhatsappStatus) {
      diagWhatsappStatus.textContent = data.whatsapp_enabled ? 'LIVE (Cloud API Connected)' : 'OFFLINE (MOCK)';
    }
  }

  // =========================================================================
  // 2. Password Change Handler
  // =========================================================================

  async function handlePasswordChange(e) {
    e.preventDefault();

    const currentPwdInput = document.getElementById('settingsCurrentPassword');
    const newPwdInput = document.getElementById('settingsNewPassword');
    const confirmPwdInput = document.getElementById('settingsConfirmPassword');
    const alertEl = document.getElementById('settingsPasswordAlert');
    const submitBtn = document.getElementById('settingsChangePasswordBtn');

    if (!currentPwdInput || !newPwdInput || !confirmPwdInput) return;

    const currentPassword = currentPwdInput.value;
    const newPassword = newPwdInput.value;
    const confirmPassword = confirmPwdInput.value;

    if (alertEl) {
      alertEl.className = 'form-alert error hidden';
      alertEl.textContent = '';
    }

    // Client-side validations
    if (!currentPassword) {
      showFormError(alertEl, 'Please enter your current administrator password.');
      currentPwdInput.focus();
      return;
    }

    if (!newPassword || newPassword.length < 8) {
      showFormError(alertEl, 'New password must be at least 8 characters long.');
      newPwdInput.focus();
      return;
    }

    if (newPassword !== confirmPassword) {
      showFormError(alertEl, 'New password and confirmation password do not match.');
      confirmPwdInput.focus();
      return;
    }

    if (newPassword === currentPassword) {
      showFormError(alertEl, 'New password must be different from current password.');
      newPwdInput.focus();
      return;
    }

    try {
      state.isSubmitting = true;
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Updating Password...';
      }

      const res = await API.post('/api/auth/change-password', {
        current_password: currentPassword,
        new_password: newPassword,
      });

      if (!res || !res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to update password.');
      }

      showToast('Password updated successfully! Other active sessions were invalidated.');
      if (alertEl) {
        alertEl.className = 'form-alert success';
        alertEl.textContent = 'Password successfully changed. Please store your new credentials securely.';
        alertEl.classList.remove('hidden');
      }

      // Reset fields
      currentPwdInput.value = '';
      newPwdInput.value = '';
      confirmPwdInput.value = '';
    } catch (err) {
      console.error('Password change error:', err);
      showFormError(alertEl, err.message || 'Error updating password.');
    } finally {
      state.isSubmitting = false;
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Change Password';
      }
    }
  }

  function showFormError(alertEl, message) {
    if (!alertEl) return;
    alertEl.className = 'form-alert error';
    alertEl.textContent = message;
    alertEl.classList.remove('hidden');
  }

  // =========================================================================
  // 3. Password Visibility Toggles & Strength Meter
  // =========================================================================

  function setupPasswordToggle(btnId, inputId, altBtnId, altInputId) {
    const btn = document.getElementById(btnId) || (altBtnId ? document.getElementById(altBtnId) : null);
    const input = document.getElementById(inputId) || (altInputId ? document.getElementById(altInputId) : null);
    if (!btn || !input) return;

    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const isPassword = input.getAttribute('type') === 'password';
      input.setAttribute('type', isPassword ? 'text' : 'password');
      btn.setAttribute('aria-label', isPassword ? 'Hide password' : 'Show password');
      btn.innerHTML = isPassword
        ? `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line></svg>`
        : `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"></path><circle cx="12" cy="12" r="3"></circle></svg>`;
    });
  }

  function evaluatePasswordStrength(password) {
    if (!password) {
      return { score: 0, text: 'Minimum 8 characters with letters, numbers & symbols', color: '#e2e8f0', width: '0%' };
    }
    let score = 0;
    if (password.length >= 8) score++;
    if (password.length >= 12) score++;
    if (/[a-z]/.test(password) && /[A-Z]/.test(password)) score++;
    if (/\d/.test(password)) score++;
    if (/[^a-zA-Z0-9]/.test(password)) score++;

    if (password.length < 8) {
      return { score: 1, text: 'Weak: Too short (minimum 8 characters required)', color: '#ef4444', width: '25%' };
    }
    if (score <= 2) {
      return { score: 2, text: 'Fair: Add uppercase letters, numbers or symbols', color: '#f59e0b', width: '50%' };
    }
    if (score === 3 || score === 4) {
      return { score: 3, text: 'Good: Strong password, almost optimal', color: '#3b82f6', width: '75%' };
    }
    return { score: 4, text: 'Strong: Excellent cryptographic complexity', color: '#10b981', width: '100%' };
  }

  function setupPasswordStrengthAndMatch() {
    const newPwdInput = document.getElementById('settingsNewPassword');
    const confirmPwdInput = document.getElementById('settingsConfirmPassword');
    const strengthBar = document.getElementById('passwordStrengthBar');
    const strengthText = document.getElementById('passwordStrengthText');
    const matchIndicator = document.getElementById('passwordMatchIndicator');

    function updateStrength() {
      if (!newPwdInput || !strengthBar || !strengthText) return;
      const res = evaluatePasswordStrength(newPwdInput.value);
      strengthBar.style.width = res.width;
      strengthBar.style.backgroundColor = res.color;
      strengthText.textContent = res.text;
      strengthText.style.color = res.score >= 3 ? 'var(--text-muted)' : res.color;
      updateMatch();
    }

    function updateMatch() {
      if (!confirmPwdInput || !newPwdInput || !matchIndicator) return;
      const pwd = newPwdInput.value;
      const confirm = confirmPwdInput.value;

      if (!confirm) {
        matchIndicator.classList.add('hidden');
        return;
      }

      matchIndicator.classList.remove('hidden');
      if (pwd === confirm) {
        matchIndicator.style.color = 'var(--success)';
        matchIndicator.innerHTML = '✓ Passwords match';
      } else {
        matchIndicator.style.color = 'var(--danger)';
        matchIndicator.innerHTML = '⚠ Passwords do not match';
      }
    }

    if (newPwdInput) newPwdInput.addEventListener('input', updateStrength);
    if (confirmPwdInput) confirmPwdInput.addEventListener('input', updateMatch);
  }

  // =========================================================================
  // 4. Module Initialization
  // =========================================================================

  function init() {
    if (state.initialized) {
      loadSettingsData();
      return;
    }

    const form = document.getElementById('changePasswordForm');
    if (form) {
      form.addEventListener('submit', handlePasswordChange);
    }

    const refreshBtn = document.getElementById('settingsRefreshBtn');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', loadSettingsData);
    }

    // Initialize password eye toggles
    setupPasswordToggle('toggleCurrentPwdBtn', 'settingsCurrentPassword', 'toggleCurrentPasswordBtn', 'currentPassword');
    setupPasswordToggle('toggleNewPwdBtn', 'settingsNewPassword', 'toggleNewPasswordBtn', 'newPassword');
    setupPasswordToggle('toggleConfirmPwdBtn', 'settingsConfirmPassword', 'toggleConfirmPasswordBtn', 'confirmPassword');

    // Initialize password strength meter & match validator
    setupPasswordStrengthAndMatch();

    state.initialized = true;
    loadSettingsData();
  }

  window.SettingsManager = {
    init,
    loadSettingsData,
  };
})();
