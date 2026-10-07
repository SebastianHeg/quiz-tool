// Desktop panel widths are independent of the mobile overlay layout.
(() => {
  const desktop = window.matchMedia('(min-width: 701px)');
  const storageKey = 'trainer_sidebar_widths';
  const minimumPanelWidth = 150;
  const maximumPanelWidth = 480;
  const minimumMainWidth = 280;
  const defaultWidths = { sidebar: 240, stats: 270 };
  const widths = loadWidths();
  const panels = [
    { name: 'sidebar', handle: document.getElementById('sidebar-resizer'), direction: 1 },
    { name: 'stats', handle: document.getElementById('stats-resizer'), direction: -1 },
  ];
  let activeDrag = null;

  function loadWidths() {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey));
      return Object.fromEntries(Object.entries(defaultWidths).map(([name, fallback]) => {
        const width = saved?.[name];
        return [name, Number.isFinite(width) ? clamp(width, minimumPanelWidth, maximumPanelWidth) : fallback];
      }));
    } catch {
      return { ...defaultWidths };
    }
  }

  function saveWidths() {
    try {
      localStorage.setItem(storageKey, JSON.stringify(widths));
    } catch {
      // Resizing still works when browser storage is unavailable.
    }
  }

  function clamp(value, minimum, maximum) {
    return Math.min(maximum, Math.max(minimum, value));
  }

  function panelBudget() {
    const handleWidth = parseFloat(getComputedStyle(document.body).getPropertyValue('--resize-handle-width'));
    return document.body.clientWidth - minimumMainWidth - 2 * handleWidth;
  }

  function visibleWidths() {
    const budget = panelBudget();
    const excess = Math.max(0, widths.sidebar + widths.stats - budget);
    const sidebarRoom = widths.sidebar - minimumPanelWidth;
    const statsRoom = widths.stats - minimumPanelWidth;
    const totalRoom = sidebarRoom + statsRoom;
    if (!excess || !totalRoom) return { ...widths };
    return {
      sidebar: widths.sidebar - excess * sidebarRoom / totalRoom,
      stats: widths.stats - excess * statsRoom / totalRoom,
    };
  }

  function renderWidths() {
    if (!desktop.matches) return;
    const visible = visibleWidths();
    for (const panel of panels) {
      const otherName = panel.name === 'sidebar' ? 'stats' : 'sidebar';
      const maximum = Math.min(maximumPanelWidth, panelBudget() - visible[otherName]);
      document.body.style.setProperty(`--${panel.name}-width`, `${visible[panel.name]}px`);
      panel.handle.setAttribute('aria-valuemin', minimumPanelWidth);
      panel.handle.setAttribute('aria-valuemax', Math.floor(maximum));
      panel.handle.setAttribute('aria-valuenow', Math.round(visible[panel.name]));
    }
  }

  function resizePanel(panel, requestedWidth) {
    const visible = visibleWidths();
    const otherName = panel.name === 'sidebar' ? 'stats' : 'sidebar';
    const maximum = Math.min(maximumPanelWidth, panelBudget() - visible[otherName]);
    widths[otherName] = visible[otherName];
    widths[panel.name] = clamp(requestedWidth, minimumPanelWidth, maximum);
    renderWidths();
  }

  function finishDrag() {
    if (!activeDrag) return;
    const { panel, pointerId } = activeDrag;
    activeDrag = null;
    document.body.classList.remove('resizing-sidebars');
    if (panel.handle.hasPointerCapture(pointerId)) panel.handle.releasePointerCapture(pointerId);
    saveWidths();
  }

  for (const panel of panels) {
    panel.handle.addEventListener('pointerdown', event => {
      if (!desktop.matches || event.button !== 0 || activeDrag) return;
      event.preventDefault();
      panel.handle.focus();
      activeDrag = {
        panel,
        pointerId: event.pointerId,
        startX: event.clientX,
        startWidth: visibleWidths()[panel.name],
      };
      panel.handle.setPointerCapture(event.pointerId);
      document.body.classList.add('resizing-sidebars');
    });

    panel.handle.addEventListener('pointermove', event => {
      if (!activeDrag || activeDrag.pointerId !== event.pointerId) return;
      const delta = (event.clientX - activeDrag.startX) * panel.direction;
      resizePanel(panel, activeDrag.startWidth + delta);
    });

    for (const eventName of ['pointerup', 'pointercancel', 'lostpointercapture']) {
      panel.handle.addEventListener(eventName, finishDrag);
    }

    panel.handle.addEventListener('keydown', event => {
      if (!desktop.matches || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const step = event.shiftKey ? 40 : 10;
      let requestedWidth = visibleWidths()[panel.name];
      if (event.key === 'Home') requestedWidth = minimumPanelWidth;
      else if (event.key === 'End') requestedWidth = maximumPanelWidth;
      else requestedWidth += (event.key === 'ArrowRight' ? step : -step) * panel.direction;
      resizePanel(panel, requestedWidth);
      saveWidths();
    });
  }

  window.addEventListener('resize', () => {
    finishDrag();
    renderWidths();
  });
  renderWidths();
})();
