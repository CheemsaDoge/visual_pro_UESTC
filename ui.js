/**
 * Unified UI Utilities for Stitch Workbench
 * Supports Toast Notifications, Confirm Dialogs, and Font Zoom
 */
(function() {
  // Ensure toast container exists
  function getToastContainer() {
    let container = document.getElementById('wb-toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'wb-toast-container';
      container.className = 'toast-container';
      document.body.appendChild(container);
    }
    return container;
  }

  // Toast types: 'success', 'error', 'info', 'warning'
  window.showToast = function(title, desc = '', type = 'info', duration = 3500) {
    const container = getToastContainer();
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;

    let iconSvg = '';
    if (type === 'success') {
      iconSvg = '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>';
    } else if (type === 'error') {
      iconSvg = '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>';
    } else if (type === 'warning') {
      iconSvg = '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>';
    } else {
      iconSvg = '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="#0ea5e9" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>';
    }

    toast.innerHTML = `
      ${iconSvg}
      <div class="toast-content">
        <div class="toast-title">${title}</div>
        ${desc ? `<div class="toast-desc">${desc}</div>` : ''}
      </div>
    `;

    container.appendChild(toast);

    const timer = setTimeout(() => {
      toast.classList.add('toast-hiding');
      setTimeout(() => toast.remove(), 250);
    }, duration);

    toast.onclick = () => {
      clearTimeout(timer);
      toast.classList.add('toast-hiding');
      setTimeout(() => toast.remove(), 200);
    };
  };

  // Custom Touch-friendly Modal Confirm (replaces window.confirm)
  window.showConfirmDialog = function({ title, message, confirmText = '确定', cancelText = '取消', onConfirm, danger = false }) {
    let backdrop = document.getElementById('wb-confirm-backdrop');
    if (!backdrop) {
      backdrop = document.createElement('div');
      backdrop.id = 'wb-confirm-backdrop';
      backdrop.className = 'modal-backdrop';
      backdrop.innerHTML = `
        <div class="modal-dialog">
          <h3 id="wb-confirm-title" style="margin:0 0 12px; font-size:1.25rem; font-weight:800;"></h3>
          <p id="wb-confirm-msg" style="margin:0 0 24px; color:var(--text-secondary); font-size:0.95rem; line-height:1.5;"></p>
          <div style="display:flex; gap:12px; justify-content:flex-end;">
            <button id="wb-confirm-cancel" class="btn btn-secondary" style="flex:1; height:46px;"></button>
            <button id="wb-confirm-ok" class="btn" style="flex:1; height:46px;"></button>
          </div>
        </div>
      `;
      document.body.appendChild(backdrop);
    }

    const titleEl = document.getElementById('wb-confirm-title');
    const msgEl = document.getElementById('wb-confirm-msg');
    const cancelBtn = document.getElementById('wb-confirm-cancel');
    const okBtn = document.getElementById('wb-confirm-ok');

    titleEl.textContent = title;
    msgEl.textContent = message;
    cancelBtn.textContent = cancelText;
    okBtn.textContent = confirmText;

    okBtn.className = `btn ${danger ? 'btn-danger' : 'btn-primary'}`;

    function close() {
      backdrop.classList.remove('show');
    }

    cancelBtn.onclick = close;
    backdrop.onclick = (e) => {
      if (e.target === backdrop) close();
    };

    okBtn.onclick = () => {
      close();
      if (typeof onConfirm === 'function') onConfirm();
    };

    backdrop.classList.add('show');
  };

  // Synchronize font size / zoom from config.ui
  window.syncFontZoom = function(fontZoom) {
    if (fontZoom && !isNaN(fontZoom)) {
      document.documentElement.style.setProperty('--font-zoom', fontZoom);
    }
  };
})();
