/**
 * Authentication Form & Route Guard Logic
 */

document.addEventListener('DOMContentLoaded', async () => {
  const loginForm = document.getElementById('loginForm');
  const usernameInput = document.getElementById('username');
  const passwordInput = document.getElementById('password');
  const togglePasswordBtn = document.getElementById('togglePasswordBtn');
  const eyeIcon = document.getElementById('eyeIcon');
  const eyeOffIcon = document.getElementById('eyeOffIcon');
  const submitBtn = document.getElementById('submitBtn');
  const btnText = document.getElementById('btnText');
  const btnSpinner = document.getElementById('btnSpinner');
  const alertBox = document.getElementById('alertBox');

  // Check URL parameters for expiration notifications
  const urlParams = new URLSearchParams(window.location.search);
  if (urlParams.get('expired') === '1') {
    showAlert('Your session has expired. Please sign in again.', 'danger');
  }

  // 1. Initial Route Guard: If user is already authenticated on /login, redirect to dashboard
  try {
    const statusRes = await API.get('/api/auth/status');
    if (statusRes && statusRes.ok) {
      const statusData = await statusRes.json();
      if (statusData.authenticated) {
        window.location.href = '/';
        return;
      }
    }
  } catch (e) {
    // Status check network failure; stay on login page
  }

  // 2. Toggle password visibility
  if (togglePasswordBtn && passwordInput) {
    togglePasswordBtn.addEventListener('click', () => {
      const isPassword = passwordInput.getAttribute('type') === 'password';
      passwordInput.setAttribute('type', isPassword ? 'text' : 'password');
      if (isPassword) {
        eyeIcon.classList.add('hidden');
        eyeOffIcon.classList.remove('hidden');
        togglePasswordBtn.setAttribute('aria-label', 'Hide password');
      } else {
        eyeIcon.classList.remove('hidden');
        eyeOffIcon.classList.add('hidden');
        togglePasswordBtn.setAttribute('aria-label', 'Show password');
      }
    });
  }

  // 3. Helper to display alerts
  function showAlert(message, type = 'danger') {
    if (!alertBox) return;
    alertBox.textContent = message;
    alertBox.className = `alert-box ${type}`;
    alertBox.classList.remove('hidden');
  }

  function hideAlert() {
    if (!alertBox) return;
    alertBox.textContent = '';
    alertBox.classList.add('hidden');
  }

  // 4. Form Submission Handler
  if (loginForm) {
    loginForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      hideAlert();

      const username = usernameInput.value.trim();
      const password = passwordInput.value;

      if (!username || !password) {
        showAlert('Please enter both your username and password.');
        return;
      }

      // Set loading state
      submitBtn.disabled = true;
      btnText.textContent = 'Signing in...';
      btnSpinner.classList.remove('hidden');

      try {
        const response = await API.post('/api/auth/login', { username, password });

        if (!response) {
          showAlert('Authentication failed. Please try again.');
          return;
        }

        if (response.ok) {
          showAlert('Sign in successful. Redirecting...', 'success');
          setTimeout(() => {
            window.location.href = '/';
          }, 400);
          return;
        }

        const data = await response.json().catch(() => ({}));

        if (response.status === 401) {
          showAlert(data.detail || 'Invalid username or password.');
        } else if (response.status === 429) {
          showAlert(data.detail || 'Too many failed login attempts. Please wait before retrying.');
        } else if (response.status === 403) {
          showAlert(data.detail || 'Account is deactivated. Contact your administrator.');
        } else {
          showAlert(data.detail || 'Sign in failed. Please check your credentials.');
        }
      } catch (err) {
        showAlert('Unable to reach authentication server. Please check your network connection.');
      } finally {
        submitBtn.disabled = false;
        btnText.textContent = 'Sign In';
        btnSpinner.classList.add('hidden');
      }
    });
  }
});
