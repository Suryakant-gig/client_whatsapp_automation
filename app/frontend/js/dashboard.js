/**
 * CRM Dashboard Controller
 * Handles authentication checks, route-aware frontend views, statistics rendering, and user interactions.
 */

document.addEventListener('DOMContentLoaded', async () => {
  // Shell elements
  const userProfileName = document.getElementById('userProfileName');
  const userRoleTag = document.getElementById('userRoleTag');
  const headerLogoutBtn = document.getElementById('headerLogoutBtn');
  const sidebarLogoutBtn = document.getElementById('sidebarLogoutBtn');
  const refreshStatsBtn = document.getElementById('refreshStatsBtn');
  const syncExcelBtn = document.getElementById('syncExcelBtn');
  const mobileMenuToggle = document.getElementById('mobileMenuToggle');
  const sidebar = document.getElementById('sidebar');
  const pageTitle = document.getElementById('pageTitle');

  // Containers
  const overviewContainer = document.getElementById('overviewContainer');
  const leadsContainer = document.getElementById('leadsContainer');
  const campaignsContainer = document.getElementById('campaignsContainer');
  const approvalsContainer = document.getElementById('approvalsContainer');
  const followupsContainer = document.getElementById('followupsContainer');
  const excelContainer = document.getElementById('excelContainer');
  const reportsContainer = document.getElementById('reportsContainer');
  const settingsContainer = document.getElementById('settingsContainer');
  const placeholderContainer = document.getElementById('placeholderContainer');

  const allContainers = [
    overviewContainer,
    leadsContainer,
    campaignsContainer,
    approvalsContainer,
    followupsContainer,
    excelContainer,
    reportsContainer,
    settingsContainer,
    placeholderContainer,
  ];

  function hideAllContainers() {
    allContainers.forEach(c => {
      if (c) c.classList.add('hidden');
    });
  }

  // Placeholder elements
  const breadcrumbModule = document.getElementById('breadcrumbModule');
  const placeholderIcon = document.getElementById('placeholderIcon');
  const placeholderPhaseBadge = document.getElementById('placeholderPhaseBadge');
  const placeholderTitle = document.getElementById('placeholderTitle');
  const placeholderSubtitle = document.getElementById('placeholderSubtitle');
  const placeholderEndpoint = document.getElementById('placeholderEndpoint');

  // Metric displays
  const statTotalLeads = document.getElementById('statTotalLeads');
  const statPendingLeads = document.getElementById('statPendingLeads');
  const statRepliedLeads = document.getElementById('statRepliedLeads');
  const statConfirmedLeads = document.getElementById('statConfirmedLeads');
  const statOptedInLeads = document.getElementById('statOptedInLeads');
  const statOptedOutLeads = document.getElementById('statOptedOutLeads');

  const statTotalCampaigns = document.getElementById('statTotalCampaigns');
  const statActiveCampaigns = document.getElementById('statActiveCampaigns');

  const statTotalMessages = document.getElementById('statTotalMessages');
  const statDeliveredMessages = document.getElementById('statDeliveredMessages');
  const statReadMessages = document.getElementById('statReadMessages');
  const statFailedMessages = document.getElementById('statFailedMessages');
  const statDeliveryRate = document.getElementById('statDeliveryRate');

  const statScheduledFollowups = document.getElementById('statScheduledFollowups');
  const lastSyncTimeEl = document.getElementById('lastSyncTime');
  const schedulerStatusTag = document.getElementById('schedulerStatusTag');
  const whatsappStatusTag = document.getElementById('whatsappStatusTag');
  const activityList = document.getElementById('activityList');

  // Module configuration registry for frontend routing
  const MODULE_ROUTES = {
    '/dashboard': {
      title: 'Overview',
      isOverview: true,
    },
    '/dashboard/leads': {
      title: 'Leads',
      isLeads: true,
    },
    '/dashboard/campaigns': {
      title: 'Campaigns',
      isCampaigns: true,
    },
    '/dashboard/excel': {
      title: 'Excel Sync',
      isExcel: true,
    },
    '/dashboard/approvals': {
      title: 'Batch Approvals',
      isApprovals: true,
    },
    '/dashboard/followups': {
      title: 'Follow-up Schedules',
      isFollowups: true,
    },
    '/dashboard/reports': {
      title: 'Delivery Reports',
      isReports: true,
    },
    '/dashboard/settings': {
      title: 'Settings',
      isSettings: true,
    },
  };

  // 1. Authenticate user & guard route
  try {
    const authRes = await API.get('/api/auth/me');
    if (!authRes || !authRes.ok) {
      window.location.href = '/login?expired=1';
      return;
    }
    const user = await authRes.json();
    if (userProfileName) userProfileName.textContent = user.username;
    if (userRoleTag) userRoleTag.textContent = user.role.toUpperCase();
    checkHeaderApiStatus();
  } catch (err) {
    window.location.href = '/login?expired=1';
    return;
  }

  // Dynamic Top Header API Status Helper
  function updateHeaderApiStatus(whatsappEnabled) {
    const headerDot = document.getElementById('headerApiStatusDot');
    const headerText = document.getElementById('headerApiStatusText');
    if (headerDot && headerText) {
      if (whatsappEnabled) {
        headerDot.className = 'status-dot active pulsing';
        headerDot.style.background = '#047857';
        headerText.textContent = 'WhatsApp API Connected';
      } else {
        headerDot.className = 'status-dot inactive';
        headerDot.style.background = '#B45309';
        headerText.textContent = 'WhatsApp API Offline (Mock Mode)';
      }
    }
  }

  async function checkHeaderApiStatus() {
    try {
      const res = await API.get('/api/dashboard/overview');
      if (res && res.ok) {
        const data = await res.json();
        updateHeaderApiStatus(data.whatsapp_enabled);
      }
    } catch {
      updateHeaderApiStatus(false);
    }
  }

  // 2. Route Rendering Controller
  function renderCurrentRoute() {
    let currentPath = window.location.pathname.toLowerCase().replace(/\/$/, '');
    if (!currentPath || currentPath === '') currentPath = '/dashboard';

    const config = MODULE_ROUTES[currentPath] || MODULE_ROUTES['/dashboard'];

    // Update active class on sidebar items
    document.querySelectorAll('.sidebar-nav .nav-item').forEach(link => {
      const targetPath = (link.getAttribute('data-path') || '').toLowerCase();
      if (targetPath === currentPath) {
        link.classList.add('active');
      } else {
        link.classList.remove('active');
      }
    });

    if (pageTitle) pageTitle.textContent = config.title;

    // Reset visibility
    hideAllContainers();

    if (config.isOverview) {
      if (overviewContainer) overviewContainer.classList.remove('hidden');
      loadDashboardData();
    } else if (config.isLeads) {
      if (leadsContainer) leadsContainer.classList.remove('hidden');
      if (window.LeadsManager) {
        window.LeadsManager.init();
      }
    } else if (config.isCampaigns) {
      if (campaignsContainer) campaignsContainer.classList.remove('hidden');
      if (window.CampaignsManager) {
        window.CampaignsManager.init();
      }
    } else if (config.isApprovals) {
      if (approvalsContainer) approvalsContainer.classList.remove('hidden');
      if (window.ApprovalsManager) {
        window.ApprovalsManager.init();
      }
    } else if (config.isFollowups) {
      if (followupsContainer) followupsContainer.classList.remove('hidden');
      if (window.FollowupsManager) {
        window.FollowupsManager.init();
      }
    } else if (config.isExcel) {
      if (excelContainer) excelContainer.classList.remove('hidden');
      if (window.ExcelSyncManager) {
        window.ExcelSyncManager.init();
      }
    } else if (config.isReports) {
      if (reportsContainer) reportsContainer.classList.remove('hidden');
      if (window.ReportsManager) {
        window.ReportsManager.init();
      }
    } else if (config.isSettings) {
      if (settingsContainer) settingsContainer.classList.remove('hidden');
      if (window.SettingsManager) {
        window.SettingsManager.init();
      }
    } else {
      if (placeholderContainer) placeholderContainer.classList.remove('hidden');
      if (breadcrumbModule) breadcrumbModule.textContent = config.title;
      if (placeholderIcon) placeholderIcon.innerHTML = config.icon || '';
      if (placeholderPhaseBadge) placeholderPhaseBadge.textContent = config.phase || 'Future Scope';
      if (placeholderTitle) placeholderTitle.textContent = config.title;
      if (placeholderSubtitle) placeholderSubtitle.textContent = config.subtitle;
      if (placeholderEndpoint) placeholderEndpoint.textContent = config.apiEndpoint || '/api/...';
    }
  }

  // Intercept navigation link clicks for smooth routing
  document.querySelectorAll('.sidebar-nav .nav-item').forEach(link => {
    link.addEventListener('click', (e) => {
      const href = link.getAttribute('href');
      if (href && href.startsWith('/dashboard')) {
        e.preventDefault();
        window.history.pushState({}, '', href);
        renderCurrentRoute();
        if (sidebar && window.innerWidth <= 768) {
          sidebar.classList.remove('open');
        }
      }
    });
  });

  window.addEventListener('popstate', renderCurrentRoute);

  // 3. Fetch and render dashboard overview stats
  async function loadDashboardData() {
    try {
      if (refreshStatsBtn) refreshStatsBtn.classList.add('loading');

      const response = await API.get('/api/dashboard/overview');
      if (!response || !response.ok) {
        const status = response ? response.status : 'Network Error';
        console.error(`[Dashboard] Failed to fetch /api/dashboard/overview (HTTP ${status})`);
        if (activityList) {
          activityList.innerHTML = `
            <div class="empty-state">
              <div class="empty-state-title" style="color: var(--danger);">Failed to load dashboard data</div>
              <div class="empty-state-text">Endpoint /api/dashboard/overview returned HTTP ${status}. Click Refresh to retry.</div>
            </div>
          `;
        }
        return;
      }

      const data = await response.json();
      const stats = data.stats || {};

      // Populate Lead metrics
      if (statTotalLeads) statTotalLeads.textContent = (stats.total_leads ?? 0).toLocaleString();
      if (statPendingLeads) statPendingLeads.textContent = (stats.pending_leads ?? 0).toLocaleString();
      if (statRepliedLeads) statRepliedLeads.textContent = (stats.replied_leads ?? 0).toLocaleString();
      if (statConfirmedLeads) statConfirmedLeads.textContent = (stats.confirmed_leads ?? 0).toLocaleString();
      if (statOptedInLeads) statOptedInLeads.textContent = (stats.opted_in_leads ?? 0).toLocaleString();
      if (statOptedOutLeads) statOptedOutLeads.textContent = (stats.opted_out_leads ?? 0).toLocaleString();

      // Populate Campaign metrics
      if (statTotalCampaigns) statTotalCampaigns.textContent = (stats.total_campaigns ?? 0).toLocaleString();
      if (statActiveCampaigns) statActiveCampaigns.textContent = (stats.active_campaigns ?? 0).toLocaleString();

      // Populate Message metrics
      const totalSent = stats.total_messages_sent ?? 0;
      const delivered = stats.delivered_messages ?? 0;
      if (statTotalMessages) statTotalMessages.textContent = totalSent.toLocaleString();
      if (statDeliveredMessages) statDeliveredMessages.textContent = delivered.toLocaleString();
      if (statReadMessages) statReadMessages.textContent = (stats.read_messages ?? 0).toLocaleString();
      if (statFailedMessages) statFailedMessages.textContent = (stats.failed_messages ?? 0).toLocaleString();

      // Delivery Rate %
      if (statDeliveryRate) {
        if (totalSent > 0) {
          const rate = Math.round((delivered / totalSent) * 100);
          statDeliveryRate.textContent = `${rate}% Delivery`;
        } else {
          statDeliveryRate.textContent = '100% Delivery';
        }
      }

      // Follow-up automation
      if (statScheduledFollowups) statScheduledFollowups.textContent = (stats.scheduled_follow_ups ?? 0).toLocaleString();

      // Last sync timestamp
      if (lastSyncTimeEl) {
        if (stats.last_sync_timestamp) {
          const syncDate = new Date(stats.last_sync_timestamp);
          lastSyncTimeEl.textContent = syncDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        } else {
          lastSyncTimeEl.textContent = 'Not yet synced';
        }
      }

      // System health status tags
      if (schedulerStatusTag) {
        if (data.scheduler_enabled) {
          schedulerStatusTag.textContent = 'ACTIVE';
          schedulerStatusTag.className = 'health-status-tag active';
        } else {
          schedulerStatusTag.textContent = 'DISABLED';
          schedulerStatusTag.className = 'health-status-tag inactive';
        }
      }

      if (whatsappStatusTag) {
        if (data.whatsapp_enabled) {
          whatsappStatusTag.textContent = 'LIVE';
          whatsappStatusTag.className = 'health-status-tag active';
        } else {
          whatsappStatusTag.textContent = 'OFFLINE (MOCK)';
          whatsappStatusTag.className = 'health-status-tag inactive';
        }
      }

      // Update top header indicator
      updateHeaderApiStatus(data.whatsapp_enabled);

      // Populate Interested Leads Call Queue widget
      renderInterestedLeadsWidget(data.interested_pending_call_count, data.latest_interested_leads);

      // Populate Activity stream
      renderRecentActivity(data.recent_activity);

    } catch (err) {
      console.error('[Dashboard] Error fetching /api/dashboard/overview:', err);
      if (activityList) {
        activityList.innerHTML = `
          <div class="empty-state">
            <div class="empty-state-title" style="color: var(--danger);">Error loading dashboard data</div>
            <div class="empty-state-text">${escapeHtml(err.message || 'Network error occurred')}. Click Refresh to retry.</div>
          </div>
        `;
      }
    } finally {
      if (refreshStatsBtn) refreshStatsBtn.classList.remove('loading');
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

  // 4a. Render Interested Leads Widget
  function renderInterestedLeadsWidget(pendingCount, leads) {
    const badge = document.getElementById('dashboardInterestedCountBadge');
    const container = document.getElementById('dashboardInterestedLeadsList');
    const count = pendingCount ?? 0;

    if (badge) {
      badge.textContent = count;
      badge.classList.toggle('empty', count === 0);
    }

    if (!container) return;

    if (!leads || leads.length === 0) {
      container.innerHTML = `
        <div class="empty-state" style="padding: 1.5rem 1rem;">
          <div class="empty-state-title" style="font-size: 0.9rem; color: #64748b;">No leads currently awaiting a callback. Inbound interested replies will appear here automatically.</div>
        </div>
      `;
      return;
    }

    container.innerHTML = leads.map(lead => {
      const phoneClean = escapeHtml(lead.phone_number);
      const replySnippet = escapeHtml(lead.last_reply_text || 'Customer expressed interest on WhatsApp');
      const istTime = formatDateTimeIST(lead.last_replied_at);

      return `
        <div class="interested-card-item">
          <div class="interested-card-left">
            <div class="interested-card-name-row">
              <strong style="color: #1e293b; font-size: 0.95rem;">${escapeHtml(lead.customer_name)}</strong>
              <span class="badge badge-interested">Interested</span>
              <span class="badge badge-call-needed">Needs Call</span>
            </div>
            <div>
              <a href="tel:${phoneClean}" class="phone-call-link"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"></path></svg> ${phoneClean}</a>
            </div>
            <div class="interested-card-snippet">
              &ldquo;${replySnippet}&rdquo;
            </div>
            <div class="interested-card-meta">
              Replied: ${istTime}
            </div>
          </div>
          <div class="interested-card-right">
            <button type="button" class="btn-action-call dash-quick-mark-called" data-id="${lead.id}" data-name="${escapeHtml(lead.customer_name)}" data-phone="${phoneClean}" data-reply="${escapeHtml(lead.last_reply_text || '')}">
              Mark Called
            </button>
          </div>
        </div>
      `;
    }).join('');
  }

  // 4. Render Activity Timeline
  function renderRecentActivity(activities) {
    if (!activityList) return;

    if (!activities || activities.length === 0) {
      activityList.innerHTML = `
        <div class="empty-state">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect>
            <line x1="8" y1="21" x2="16" y2="21"></line>
            <line x1="12" y1="17" x2="12" y2="21"></line>
          </svg>
          <div class="empty-state-title">No Recent Activity</div>
          <div class="empty-state-text">New WhatsApp dispatches, incoming messages, and sync jobs will appear here automatically.</div>
        </div>
      `;
      return;
    }

    activityList.innerHTML = activities.map(item => {
      let iconSvg = '';
      if (item.category === 'message') {
        iconSvg = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"></path></svg>`;
      } else if (item.category === 'incoming') {
        iconSvg = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>`;
      } else {
        iconSvg = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"></path></svg>`;
      }

      const dateObj = new Date(item.timestamp);
      const formattedTime = dateObj.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

      let badgeClass = 'badge-sent';
      const statusLower = (item.status || '').toLowerCase();
      if (statusLower.includes('delivered') || statusLower === 'success') badgeClass = 'badge-delivered';
      else if (statusLower.includes('read')) badgeClass = 'badge-read';
      else if (statusLower.includes('failed')) badgeClass = 'badge-failed';

      return `
        <div class="activity-item">
          <div class="activity-icon ${item.category}">
            ${iconSvg}
          </div>
          <div class="activity-details">
            <div class="activity-title-row">
              <span class="activity-title">${escapeHtml(item.title)}</span>
              <span class="activity-time">${formattedTime}</span>
            </div>
            <div class="activity-desc">
              ${escapeHtml(item.description)}
              ${item.status ? `<span class="activity-badge ${badgeClass}">${escapeHtml(item.status)}</span>` : ''}
            </div>
          </div>
        </div>
      `;
    }).join('');
  }

  function escapeHtml(text) {
    if (!text) return '';
    return text.replace(/[&<>"']/g, m => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#039;'
    })[m]);
  }

  // 5. Logout handler
  async function handleLogout() {
    try {
      await API.post('/api/auth/logout');
    } catch (e) {
      console.warn('Logout network error');
    }
    window.location.href = '/login';
  }

  if (headerLogoutBtn) headerLogoutBtn.addEventListener('click', handleLogout);
  if (sidebarLogoutBtn) sidebarLogoutBtn.addEventListener('click', handleLogout);

  // 6. Refresh action
  if (refreshStatsBtn) {
    refreshStatsBtn.addEventListener('click', () => {
      loadDashboardData();
    });
  }

  // 7. Excel sync action
  if (syncExcelBtn) {
    syncExcelBtn.addEventListener('click', async () => {
      try {
        syncExcelBtn.disabled = true;
        syncExcelBtn.textContent = 'Syncing...';
        const res = await API.post('/api/excel/sync', {});
        if (res && res.ok) {
          alert('Excel workbook successfully synchronized with database!');
          loadDashboardData();
        } else {
          const errData = await res.json().catch(() => ({}));
          alert(errData.detail || 'Workbook synchronization failed');
        }
      } catch (err) {
        alert('Network error while requesting workbook synchronization');
      } finally {
        syncExcelBtn.disabled = false;
        syncExcelBtn.textContent = 'Sync Workbook';
      }
    });
  }

  // 8. Mobile menu toggle
  if (mobileMenuToggle && sidebar) {
    mobileMenuToggle.addEventListener('click', () => {
      sidebar.classList.toggle('open');
    });
  }

  // 9. Interested Leads Queue interactions on Dashboard Overview
  const interestedContainer = document.getElementById('dashboardInterestedLeadsList');
  if (interestedContainer) {
    interestedContainer.addEventListener('click', (e) => {
      const btn = e.target.closest('.dash-quick-mark-called');
      if (btn) {
        e.preventDefault();
        const leadId = btn.getAttribute('data-id');
        const name = btn.getAttribute('data-name');
        const phone = btn.getAttribute('data-phone');
        const reply = btn.getAttribute('data-reply');
        if (window.LeadsManager && window.LeadsManager.openMarkCalledModal) {
          window.LeadsManager.openMarkCalledModal(leadId, name, phone, reply);
        }
      }
    });
  }

  const viewAllInterestedLink = document.getElementById('viewAllInterestedLink');
  if (viewAllInterestedLink) {
    viewAllInterestedLink.addEventListener('click', (e) => {
      e.preventDefault();
      window.history.pushState({}, '', '/dashboard/leads?tab=interested');
      renderCurrentRoute();
      if (window.LeadsManager) {
        window.LeadsManager.switchQueueTab('interested');
      }
    });
  }

  // Expose loadDashboardData for cross-module refreshes
  window.loadDashboardData = loadDashboardData;

  // Initial route execution
  renderCurrentRoute();
});
