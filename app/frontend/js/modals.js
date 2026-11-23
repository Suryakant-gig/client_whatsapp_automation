/**
 * Centralized Modal & Dialog Manager (Phase 9.6)
 * Provides reliable, bulletproof modal opening, closing, keyboard navigation (Escape),
 * backdrop clicking, and focus restoration across all dashboard modules.
 */

(function () {
  'use strict';

  let lastActiveElement = null;

  const ModalManager = {
    /**
     * Open a modal dialog.
     * @param {string|HTMLElement} modalTarget - CSS selector or HTMLElement of the modal backdrop.
     */
    open: function (modalTarget) {
      const modal = typeof modalTarget === 'string'
        ? document.querySelector(modalTarget)
        : modalTarget;

      if (!modal) {
        console.warn('[ModalManager] Cannot open modal: Element not found', modalTarget);
        return;
      }

      // Save current focus to restore on close
      lastActiveElement = document.activeElement;

      // Reset any form alerts inside the modal
      modal.querySelectorAll('.form-alert').forEach(el => el.classList.add('hidden'));

      modal.classList.remove('hidden');
      document.body.classList.add('modal-open');

      // Accessible autofocus on first input or close button
      const focusable = modal.querySelector('input:not([type="hidden"]), select, textarea, button.btn-action-primary, button.modal-close-btn');
      if (focusable) {
        setTimeout(() => focusable.focus(), 50);
      }

      // Dispatch custom event
      modal.dispatchEvent(new CustomEvent('modal:opened', { bubbles: true }));
    },

    /**
     * Close a modal dialog.
     * @param {string|HTMLElement} modalTarget - CSS selector or HTMLElement of the modal backdrop.
     */
    close: function (modalTarget) {
      const modal = typeof modalTarget === 'string'
        ? document.querySelector(modalTarget)
        : modalTarget;

      if (!modal) return;

      modal.classList.add('hidden');

      // Check if any other modal is still visible
      const anyOpen = document.querySelector('.modal-backdrop:not(.hidden)');
      if (!anyOpen) {
        document.body.classList.remove('modal-open');
      }

      // Restore focus to previous triggering control
      if (lastActiveElement && typeof lastActiveElement.focus === 'function') {
        try {
          lastActiveElement.focus();
        } catch (_) {}
      }

      // Dispatch custom event
      modal.dispatchEvent(new CustomEvent('modal:closed', { bubbles: true }));
    },

    /**
     * Close all open modal dialogs.
     */
    closeAll: function () {
      document.querySelectorAll('.modal-backdrop:not(.hidden)').forEach(modal => {
        modal.classList.add('hidden');
        modal.dispatchEvent(new CustomEvent('modal:closed', { bubbles: true }));
      });
      document.body.classList.remove('modal-open');
    },

    /**
     * Check if a specific modal is open.
     */
    isOpen: function (modalTarget) {
      const modal = typeof modalTarget === 'string'
        ? document.querySelector(modalTarget)
        : modalTarget;
      return modal ? !modal.classList.contains('hidden') : false;
    },
  };

  // =========================================================================
  // Global Event Delegation for 100% Reliable Modal Controls
  // =========================================================================

  document.addEventListener('DOMContentLoaded', () => {
    // 1. Delegated click on any Close or Cancel button across the entire DOM
    document.addEventListener('click', (e) => {
      // Find matching close trigger
      const closeTrigger = e.target.closest(
        '[data-dismiss="modal"], .modal-close-btn, .btn-modal-close, .modal-cancel-btn'
      );

      if (closeTrigger) {
        e.preventDefault();
        e.stopPropagation();

        // Find parent modal backdrop
        const modal = closeTrigger.closest('.modal-backdrop');
        if (modal) {
          ModalManager.close(modal);
        }
        return;
      }

      // 2. Click outside (Backdrop Click) to close dismissible modals
      if (e.target.classList.contains('modal-backdrop')) {
        // Only close if modal is not marked as static
        if (e.target.getAttribute('data-static') !== 'true') {
          ModalManager.close(e.target);
        }
      }
    });

    // 3. Global Escape key handling
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' || e.key === 'Esc') {
        const openModals = Array.from(document.querySelectorAll('.modal-backdrop:not(.hidden)'));
        if (openModals.length > 0) {
          // Close topmost open modal
          const topModal = openModals[openModals.length - 1];
          if (topModal.getAttribute('data-static') !== 'true') {
            e.preventDefault();
            ModalManager.close(topModal);
          }
        }
      }
    });
  });

  // Export to global namespace
  window.ModalManager = ModalManager;
  window.Modal = ModalManager; // Convenient alias
})();
