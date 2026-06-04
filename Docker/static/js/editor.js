/**
 * Artist logo generator - Frontend Controller
 */

let currentKey = "";
let selectedUrl = "";
let currentCase = "none";
let selectedColor = "#FFFFFF";
let selectedFont = "Roboto"; // Default font
let selectedImageColor = null;
let lastChecked = null;
let selectedArtists = new Set();
let lastSelectedArtist = null;
let fanartLogos = [];
let fanartPage = 1;
let maLogos = [];
let maPage = 1;
let tadbLogos = [];
let tadbPage = 1;
let currentStatusFilter = 'all';
let lightboxImages = [];
let lightboxIndex = 0;

// --- INITIALIZATION ---

document.addEventListener("DOMContentLoaded", () => {
  initColorPicker();
  initImageColorPicker();
  // Initialize overlay/background to default (black, invisible overlay)
  const overlay = document.getElementById('preview-overlay');
  const previewContainer = document.getElementById('preview-container');
  if (overlay) {
    overlay.style.backgroundColor = selectedImageColor || '#000000';
    // hide overlay for black or white selection; show for other colours
    const sel = (selectedImageColor || '').toLowerCase();
    overlay.style.opacity = (sel && sel !== '#000000' && sel !== '#ffffff') ? '0.6' : '0';
  }
  if (previewContainer) previewContainer.style.background = '#000000';
  setupEventListeners();
  initTheme();
});

function initTheme() {
    const themeSwitcher = document.getElementById('theme-switcher');
    const savedTheme = localStorage.getItem('theme') || 'dark';
    document.body.setAttribute('data-theme', savedTheme);

    themeSwitcher.addEventListener('click', () => {
        let currentTheme = document.body.getAttribute('data-theme');
        const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
        document.body.setAttribute('data-theme', newTheme);
        localStorage.setItem('theme', newTheme);
    });
}

function setupEventListeners() {
  // Keyboard Navigation (Arrows)
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
    const lb = document.getElementById('lightbox');
    const lbOpen = lb && !lb.classList.contains('hidden');
    if (lbOpen) {
      // When lightbox is open, use arrows to navigate lightbox and prevent global navigation
      if (e.key === 'ArrowLeft') { e.preventDefault(); lightboxPrev(e); return; }
      if (e.key === 'ArrowRight') { e.preventDefault(); lightboxNext(e); return; }
      if (e.key === 'Escape') { e.preventDefault(); closeLightbox(); return; }
      return;
    }
    if (e.key === "ArrowLeft") navigateArtist(-1);
    if (e.key === "ArrowDown") navigateArtist(-10);
    if (e.key === "ArrowRight") navigateArtist(1);
    if (e.key === "ArrowUp") navigateArtist(10);
  });

  // Mobile menu
    const menuToggle = document.getElementById('menu-toggle');
    const sidebar = document.getElementById('artist-sidebar');
    const overlay = document.getElementById('mobile-menu-overlay');

    if (menuToggle && sidebar && overlay) {
        menuToggle.addEventListener('click', () => {
            sidebar.classList.toggle('sidebar-visible');
            overlay.classList.toggle('hidden');
            if (sidebar.classList.contains('sidebar-visible')) {
                menuToggle.textContent = '×';
            } else {
                menuToggle.textContent = '☰';
            }
        });

        overlay.addEventListener('click', () => {
            sidebar.classList.remove('sidebar-visible');
            overlay.classList.add('hidden');
            menuToggle.textContent = '☰';
        });
    }

    // Status filter button
    const filterBtn = document.getElementById('filter-status-btn');
    if (filterBtn) {
      filterBtn.addEventListener('click', () => {
        if (currentStatusFilter === 'all') {
          currentStatusFilter = 'done'; // Green
          filterBtn.textContent = 'Done';
          filterBtn.className = 'filter-btn status-done';
        } else if (currentStatusFilter === 'done') {
          currentStatusFilter = 'custom'; // Blue
          filterBtn.textContent = 'Custom font';
          filterBtn.className = 'filter-btn status-custom';
        } else if (currentStatusFilter === 'custom') {
          currentStatusFilter = 'none'; // Red
          filterBtn.textContent = 'To-do';
          filterBtn.className = 'filter-btn status-none';
        } else { // from 'none'
          currentStatusFilter = 'all';
          filterBtn.textContent = 'Show All';
          filterBtn.className = 'filter-btn';
        }
        filterArtists();
      });
    }

    // Image tool buttons
    const invertBtn = document.getElementById('btn-invert');
    if (invertBtn) {
        invertBtn.addEventListener('click', () => {
            invertBtn.classList.toggle('active');
            updateCSS();
        });
    }
    const monochromeBtn = document.getElementById('btn-monochrome');
    if (monochromeBtn) {
        monochromeBtn.addEventListener('click', () => {
            monochromeBtn.classList.toggle('active');
            updateCSS();
        });
    }

    // Restore clickable status-dot toggles via event delegation (works even if inline onclick is missing)
    const artistListEl = document.getElementById('artist-list');
    if (artistListEl) {
      artistListEl.addEventListener('click', (e) => {
        const t = e.target;
        if (t && t.classList && t.classList.contains('status-dot')) {
          const parent = t.closest('.artist-item');
          if (parent) {
            const key = parent.id.replace('item-', '');
            // delegate to existing toggleStatus (it stops propagation itself)
            toggleStatus(e, key);
          }
        }
      });
    }

    // Current image click -> open lightbox large preview
    const plexImgEl = document.getElementById('plex-img');
    const lightboxEl = document.getElementById('lightbox');
    const lightboxImg = document.getElementById('lightbox-img');
    if (plexImgEl) {
      plexImgEl.style.cursor = 'zoom-in';
      plexImgEl.addEventListener('click', async (ev) => {
        if (!plexImgEl.src) return;
        // Try to fetch Plex posters for this artist (same-origin proxy)
        try {
          const res = await fetch(`/get_posters/${currentKey}`);
          const data = await res.json();
          const imgs = Array.isArray(data.posters) && data.posters.length ? data.posters.slice() : [];
          // fallback to fanart logos or current image
          if (!imgs.length && Array.isArray(fanartLogos) && fanartLogos.length) imgs.push(...fanartLogos);
          if (!imgs.includes(plexImgEl.src)) imgs.unshift(plexImgEl.src);
          populateLightbox(imgs, 0, plexImgEl.src);
          if (lightboxEl) lightboxEl.classList.remove('hidden');
        } catch (e) {
          // fallback: show current image only
          populateLightbox([plexImgEl.src], 0, plexImgEl.src);
          if (lightboxEl) lightboxEl.classList.remove('hidden');
        }
      });
    }

    // Close on ESC key
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        closeLightbox();
      }
    });

    // Drag-and-drop image/SVG onto preview (works for files from file managers)
    const dropTarget = document.getElementById('preview-container');
    if (dropTarget) {
      dropTarget.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropTarget.classList.add('drag-over');
      });
      dropTarget.addEventListener('dragleave', (e) => {
        if (!dropTarget.contains(e.relatedTarget)) dropTarget.classList.remove('drag-over');
      });
      dropTarget.addEventListener('drop', async (e) => {
        e.preventDefault();
        dropTarget.classList.remove('drag-over');
        if (!currentKey) return showToast('Select an artist first', 'error');
        const file = Array.from(e.dataTransfer.files)
          .find(f => f.type.startsWith('image/') || f.name.toLowerCase().endsWith('.svg'));
        if (!file) return showToast('Drop an image or SVG file', 'error');
        const reader = new FileReader();
        reader.onload = async (ev) => {
          const isSvg = file.type === 'image/svg+xml' || file.name.toLowerCase().endsWith('.svg')
            || ev.target.result.startsWith('data:image/svg+xml');
          const dataUrl = isSvg ? await convertSvgToPng(ev.target.result) : ev.target.result;
          selectedUrl = dataUrl;
          document.getElementById('preview-img').src = selectedUrl;
          window.resetFilters && window.resetFilters();
          showToast(isSvg ? 'SVG dropped!' : 'Image dropped!');
        };
        reader.readAsDataURL(file);
      });
    }

    // Paste image from clipboard (only when an artist is loaded)
    document.addEventListener('paste', (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
      if (!currentKey) return;

      // File managers paste SVG files via clipboardData.files, not as image/* items
      const pastedFiles = e.clipboardData.files;
      const fileFromClipboard = pastedFiles && pastedFiles.length > 0
        ? (Array.from(pastedFiles).find(f => f.type === 'image/svg+xml' || f.name.toLowerCase().endsWith('.svg'))
           || Array.from(pastedFiles).find(f => f.type.startsWith('image/')))
        : null;

      const item = fileFromClipboard
        ? null
        : Array.from(e.clipboardData.items).find(i => i.type.startsWith('image/'));

      if (!fileFromClipboard && !item) return showToast('No image in clipboard', 'error');
      e.preventDefault();

      const file = fileFromClipboard || item.getAsFile();
      if (!file) return showToast('Could not read image from clipboard', 'error');

      const reader = new FileReader();
      reader.onerror = () => showToast('Failed to read clipboard image', 'error');
      reader.onload = async (ev) => {
        const isSvg = (file.type === 'image/svg+xml')
          || (file.name && file.name.toLowerCase().endsWith('.svg'))
          || ev.target.result.startsWith('data:image/svg+xml');
        const dataUrl = isSvg ? await convertSvgToPng(ev.target.result) : ev.target.result;
        selectedUrl = dataUrl;
        document.getElementById('preview-img').src = selectedUrl;
        window.resetFilters && window.resetFilters();
        const converted = isSvg && !dataUrl.startsWith('data:image/svg+xml');
        showToast(isSvg ? (converted ? 'SVG converted to PNG!' : 'SVG pasted — will convert on save') : 'Image pasted!');
      };
      reader.readAsDataURL(file);
    });
}

function selectFont(fontName) {
    selectedFont = fontName;

    // Update UI
    document.querySelectorAll('.font-btn').forEach(btn => {
        if (btn.textContent === fontName) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });

    previewCustom();
}

function setRows(n) {
  const input = document.getElementById('row-count');
  if (input) input.value = n;
  document.querySelectorAll('.row-btn').forEach(b => {
    if (parseInt(b.textContent) === n) b.classList.add('active'); else b.classList.remove('active');
  });
  previewCustom();
}

window.initColorPicker = window.initColorPicker || function() { console.warn('initColorPicker: implemented in colorpicker.js'); };

window.initImageColorPicker = window.initImageColorPicker || function() { console.warn('initImageColorPicker: implemented in colorpicker.js'); };

window.populateLightbox = window.populateLightbox || function() { console.warn('populateLightbox: implemented in lightbox.js'); };
window.updateLightbox = window.updateLightbox || function() { console.warn('updateLightbox: implemented in lightbox.js'); };
window.lightboxPrev = window.lightboxPrev || function() { console.warn('lightboxPrev: implemented in lightbox.js'); };
window.lightboxNext = window.lightboxNext || function() { console.warn('lightboxNext: implemented in lightbox.js'); };
window.saveFromLightbox = window.saveFromLightbox || function() { console.warn('saveFromLightbox: implemented in lightbox.js'); };
window.closeLightbox = window.closeLightbox || function() { console.warn('closeLightbox: implemented in lightbox.js'); };

// --- NAVIGATION & SIDEBAR ---

function updateSelectionUI() {
    document.querySelectorAll('.artist-item').forEach(item => {
        const key = item.id.replace('item-', '');
        if (selectedArtists.has(key)) {
            item.classList.add('selected');
            item.querySelector('.artist-checkbox').checked = true;
        } else {
            item.classList.remove('selected');
            item.querySelector('.artist-checkbox').checked = false;
        }
    });

    const bulkApplyBtn = document.getElementById('bulk-apply-fanart');
    const bulkToggleBtn = document.getElementById('bulk-toggle-status');
    if (selectedArtists.size > 1) {
        bulkApplyBtn.style.display = 'block';
        bulkToggleBtn.style.display = 'block';
    } else {
        bulkApplyBtn.style.display = 'none';
        bulkToggleBtn.style.display = 'none';
    }
    
    document.getElementById('select-all').checked = selectedArtists.size === document.querySelectorAll('.artist-item:not([style*="display: none"])').length;
}

function handleSelection(event, key) {
    event.stopPropagation(); // Stop it from bubbling up to the main div's loadArtist click
    const artistItems = Array.from(document.querySelectorAll('.artist-item:not([style*="display: none"])'));
    const clickedIndex = artistItems.findIndex(item => item.id === `item-${key}`);

    if (event.shiftKey && lastSelectedArtist) {
        const lastIndex = artistItems.findIndex(item => item.id === `item-${lastSelectedArtist}`);
        const [start, end] = [clickedIndex, lastIndex].sort((a, b) => a - b);
        for (let i = start; i <= end; i++) {
            const itemKey = artistItems[i].id.replace('item-', '');
            selectedArtists.add(itemKey);
        }
    } else { // This will handle normal clicks and ctrl/meta clicks
        if (selectedArtists.has(key)) {
            selectedArtists.delete(key);
        } else {
            selectedArtists.add(key);
        }
    }

    lastSelectedArtist = `item-${key}`;
    updateSelectionUI();
}

function selectAllArtists(checked) {
    const visibleItems = document.querySelectorAll('.artist-item:not([style*="display: none"])');
    if (checked) {
        visibleItems.forEach(item => {
            const key = item.id.replace('item-', '');
            selectedArtists.add(key);
        });
    } else {
        visibleItems.forEach(item => {
            const key = item.id.replace('item-', '');
            selectedArtists.delete(key);
        });
    }
    updateSelectionUI();
}

function filterArtists() {
    const q = document.getElementById("artist-search").value.toLowerCase();

    document.querySelectorAll(".artist-item").forEach((i) => {
        const status = i.getAttribute("data-status");
        const matchesSearch = i.getAttribute("data-name").toLowerCase().includes(q);
        
        let matchesStatus = false;
        if (currentStatusFilter === 'all') {
            matchesStatus = true;
        } else {
            matchesStatus = (status === currentStatusFilter);
        }

        i.style.display = matchesSearch && matchesStatus ? "flex" : "none";
    });
}

function navigateArtist(direction) {
  const visibleItems = Array.from(
    document.querySelectorAll(".artist-item"),
  ).filter((i) => i.style.display !== "none");
  const currentIndex = visibleItems.findIndex(
    (i) => i.id === `item-${currentKey}`,
  );
  const nextIndex = currentIndex + direction;

  if (nextIndex >= 0 && nextIndex < visibleItems.length) {
    const nextItem = visibleItems[nextIndex];
    loadArtist(
      nextItem.id.replace("item-", ""),
      nextItem.getAttribute("data-name"),
    );
  }
}

async function loadArtist(key, name) {
  currentKey = key;

  // UI Updates
  document
    .querySelectorAll(".artist-item")
    .forEach((i) => i.classList.remove("active"));
  const activeItem = document.getElementById(`item-${key}`);
  activeItem.classList.add("active");
  activeItem.scrollIntoView({ block: "nearest", behavior: "smooth" });

  document.getElementById("current-artist").innerText = name;
  document.getElementById("plex-img").src =
    `/plex_proxy/${key}?t=${Date.now()}`;
  // Always show fanart tab when loading a new artist
  EXCLUSIVE_PANELS.forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    if (id === 'fanart-controls') {
      el.classList.remove('hidden');
    } else {
      el.classList.add('hidden');
      if (id === 'controls-panel') el.style.display = 'none';
    }
  });
  document.querySelectorAll('.section-btn').forEach(btn => {
    const onclick = btn.getAttribute('onclick') || '';
    btn.classList.toggle('active',
      onclick.includes("toggleExclusive('fanart-controls')") || onclick.includes('toggleExclusive("fanart-controls")'));
  });

  // Fetch Fanart Options
  const res = await fetch(`/get_options/${key}`);
  const data = await res.json();
  fanartLogos = data.logos;
  fanartPage = 1;
  renderFanartPage();

  // Fetch Metal Archives logos asynchronously (HEAD-probing can be slow)
  maLogos = [];
  maPage = 1;
  renderMAPage();
  const maBtn = document.getElementById('ma-tab-btn');
  function setMABtnUnavailable() {
    if (!maBtn) return;
    maBtn.style.opacity = '0.35';
    maBtn.style.pointerEvents = 'none';
    maBtn.style.cursor = 'not-allowed';
  }
  function setMABtnAvailable() {
    if (!maBtn) return;
    maBtn.style.opacity = '';
    maBtn.style.pointerEvents = '';
    maBtn.style.cursor = '';
  }
  setMABtnUnavailable();
  fetch(`/get_metal_archives/${key}`)
    .then(r => r.json())
    .then(d => {
      maLogos = d.logos || [];
      maPage = 1;
      renderMAPage();
      if (maLogos.length > 0) setMABtnAvailable(); else setMABtnUnavailable();
    })
    .catch(() => setMABtnUnavailable());

  // Fetch TheAudioDB images asynchronously
  tadbLogos = [];
  tadbPage = 1;
  renderTADBPage();
  const tadbBtn = document.getElementById('tadb-tab-btn');
  function setTADBBtnUnavailable() {
    if (!tadbBtn) return;
    tadbBtn.style.opacity = '0.35';
    tadbBtn.style.pointerEvents = 'none';
    tadbBtn.style.cursor = 'not-allowed';
  }
  function setTADBBtnAvailable() {
    if (!tadbBtn) return;
    tadbBtn.style.opacity = '';
    tadbBtn.style.pointerEvents = '';
    tadbBtn.style.cursor = '';
  }
  setTADBBtnUnavailable();
  fetch(`/get_theaudiodb/${key}`)
    .then(r => r.json())
    .then(d => {
      tadbLogos = d.logos || [];
      tadbPage = 1;
      renderTADBPage();
      if (tadbLogos.length > 0) setTADBBtnAvailable(); else setTADBBtnUnavailable();
    })
    .catch(() => setTADBBtnUnavailable());

  // Close sidebar on mobile after selection
    if (window.innerWidth <= 800) {
        const sidebar = document.getElementById('artist-sidebar');
        const overlay = document.getElementById('mobile-menu-overlay');
        const menuToggle = document.getElementById('menu-toggle');
        sidebar.classList.remove('sidebar-visible');
        overlay.classList.add('hidden');
        menuToggle.textContent = '☰';
    }
}

function renderFanartPage() {
    const grid = document.getElementById("options-grid");
    grid.innerHTML = "";
    const paginationControls = document.getElementById("fanart-pagination");
    paginationControls.innerHTML = "";
  // Responsive columns and page size (default 3x3 = 9)
  const w = window.innerWidth;
  let cols = 3, rows = 3;
  if (w >= 1200) { cols = 3; rows = 3; }
  else if (w >= 900) { cols = 3; rows = 3; }
  else if (w >= 700) { cols = 3; rows = 2; }
  else if (w >= 500) { cols = 2; rows = 2; }
  else { cols = 1; rows = 1; }
  const pageSize = Math.min(9, cols * rows);
  grid.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;
  const logosToShow = fanartLogos.slice((fanartPage - 1) * pageSize, fanartPage * pageSize);

  logosToShow.forEach(u => {
    const img = document.createElement("img");
    const proxy = `/proxy_image?url=${encodeURIComponent(u)}`;
    img.src = proxy;
    img.className = "logo-option";
    img.onclick = () => {
      selectedUrl = u;
      document.getElementById("preview-img").src = proxy;
      resetFilters();
    };
    grid.appendChild(img);
  });

  // Pagination controls: always render prev/page/next in the same place
  const totalPages = Math.max(1, Math.ceil(fanartLogos.length / pageSize));
  const prevButton = document.createElement('button');
  prevButton.className = 'pagination-btn';
  prevButton.innerText = '<';
  prevButton.disabled = fanartPage <= 1;
  prevButton.onclick = () => {
    if (fanartPage > 1) {
      fanartPage--;
      renderFanartPage();
    }
  };

  const pageIndicator = document.createElement('span');
  pageIndicator.innerText = `Page ${fanartPage} of ${totalPages}`;

  const nextButton = document.createElement('button');
  nextButton.className = 'pagination-btn';
  nextButton.innerText = '>';
  nextButton.disabled = fanartPage >= totalPages;
  nextButton.onclick = () => {
    if (fanartPage < totalPages) {
      fanartPage++;
      renderFanartPage();
    }
  };

  // Center these controls under the logo grid
  paginationControls.appendChild(prevButton);
  paginationControls.appendChild(pageIndicator);
  paginationControls.appendChild(nextButton);

  // Touch / swipe support for the logo grid
  let touchStartX = null;
  const threshold = 40; // px
  grid.ontouchstart = (e) => { touchStartX = e.changedTouches[0].clientX; };
  grid.ontouchend = (e) => {
    if (touchStartX === null) return;
    const touchEndX = e.changedTouches[0].clientX;
    const diff = touchEndX - touchStartX;
    if (diff > threshold) {
      // swipe right -> previous
      if (fanartPage > 1) { fanartPage--; renderFanartPage(); }
    } else if (diff < -threshold) {
      // swipe left -> next
      if (fanartPage < totalPages) { fanartPage++; renderFanartPage(); }
    }
    touchStartX = null;
  };
}

function renderMAPage() {
  const grid = document.getElementById("ma-grid");
  const paginationControls = document.getElementById("ma-pagination");
  if (!grid || !paginationControls) return;
  while (grid.firstChild) grid.removeChild(grid.firstChild);
  while (paginationControls.firstChild) paginationControls.removeChild(paginationControls.firstChild);

  if (!maLogos.length) {
    const msg = document.createElement('p');
    msg.style.cssText = 'opacity:0.5; font-size:13px; padding:10px;';
    msg.textContent = 'No logos found on Metal Archives.';
    grid.appendChild(msg);
    return;
  }

  const w = window.innerWidth;
  let cols = 3, rows = 3;
  if (w >= 700) { cols = 3; rows = 3; }
  else if (w >= 500) { cols = 2; rows = 2; }
  else { cols = 1; rows = 1; }
  const pageSize = Math.min(9, cols * rows);
  grid.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;

  const logosToShow = maLogos.slice((maPage - 1) * pageSize, maPage * pageSize);
  logosToShow.forEach(u => {
    const img = document.createElement("img");
    const proxy = `/proxy_image?url=${encodeURIComponent(u)}`;
    img.src = proxy;
    img.className = "logo-option";
    img.onclick = () => {
      selectedUrl = u;
      document.getElementById("preview-img").src = proxy;
      resetFilters();
    };
    grid.appendChild(img);
  });

  const totalPages = Math.max(1, Math.ceil(maLogos.length / pageSize));
  const prevButton = document.createElement('button');
  prevButton.className = 'pagination-btn';
  prevButton.textContent = '<';
  prevButton.disabled = maPage <= 1;
  prevButton.onclick = () => { if (maPage > 1) { maPage--; renderMAPage(); } };

  const pageIndicator = document.createElement('span');
  pageIndicator.textContent = `Page ${maPage} of ${totalPages}`;

  const nextButton = document.createElement('button');
  nextButton.className = 'pagination-btn';
  nextButton.textContent = '>';
  nextButton.disabled = maPage >= totalPages;
  nextButton.onclick = () => { if (maPage < totalPages) { maPage++; renderMAPage(); } };

  paginationControls.appendChild(prevButton);
  paginationControls.appendChild(pageIndicator);
  paginationControls.appendChild(nextButton);

  let touchStartX = null;
  const threshold = 40;
  grid.ontouchstart = (e) => { touchStartX = e.changedTouches[0].clientX; };
  grid.ontouchend = (e) => {
    if (touchStartX === null) return;
    const diff = e.changedTouches[0].clientX - touchStartX;
    if (diff > threshold && maPage > 1) { maPage--; renderMAPage(); }
    else if (diff < -threshold && maPage < totalPages) { maPage++; renderMAPage(); }
    touchStartX = null;
  };
}

function renderTADBPage() {
  const grid = document.getElementById("tadb-grid");
  const paginationControls = document.getElementById("tadb-pagination");
  if (!grid || !paginationControls) return;
  while (grid.firstChild) grid.removeChild(grid.firstChild);
  while (paginationControls.firstChild) paginationControls.removeChild(paginationControls.firstChild);

  if (!tadbLogos.length) {
    const msg = document.createElement('p');
    msg.style.cssText = 'opacity:0.5; font-size:13px; padding:10px;';
    msg.textContent = 'No images found on TheAudioDB.';
    grid.appendChild(msg);
    return;
  }

  const w = window.innerWidth;
  let cols = 3, rows = 3;
  if (w >= 700) { cols = 3; rows = 3; }
  else if (w >= 500) { cols = 2; rows = 2; }
  else { cols = 1; rows = 1; }
  const pageSize = Math.min(9, cols * rows);
  grid.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;

  const logosToShow = tadbLogos.slice((tadbPage - 1) * pageSize, tadbPage * pageSize);
  logosToShow.forEach(u => {
    const img = document.createElement("img");
    const proxy = `/proxy_image?url=${encodeURIComponent(u)}`;
    img.src = proxy;
    img.className = "logo-option";
    img.onclick = () => {
      selectedUrl = u;
      document.getElementById("preview-img").src = proxy;
      resetFilters();
    };
    grid.appendChild(img);
  });

  const totalPages = Math.max(1, Math.ceil(tadbLogos.length / pageSize));
  const prevButton = document.createElement('button');
  prevButton.className = 'pagination-btn';
  prevButton.textContent = '<';
  prevButton.disabled = tadbPage <= 1;
  prevButton.onclick = () => { if (tadbPage > 1) { tadbPage--; renderTADBPage(); } };

  const pageIndicator = document.createElement('span');
  pageIndicator.textContent = `Page ${tadbPage} of ${totalPages}`;

  const nextButton = document.createElement('button');
  nextButton.className = 'pagination-btn';
  nextButton.textContent = '>';
  nextButton.disabled = tadbPage >= totalPages;
  nextButton.onclick = () => { if (tadbPage < totalPages) { tadbPage++; renderTADBPage(); } };

  paginationControls.appendChild(prevButton);
  paginationControls.appendChild(pageIndicator);
  paginationControls.appendChild(nextButton);

  let touchStartX = null;
  const threshold = 40;
  grid.ontouchstart = (e) => { touchStartX = e.changedTouches[0].clientX; };
  grid.ontouchend = (e) => {
    if (touchStartX === null) return;
    const diff = e.changedTouches[0].clientX - touchStartX;
    if (diff > threshold && tadbPage > 1) { tadbPage--; renderTADBPage(); }
    else if (diff < -threshold && tadbPage < totalPages) { tadbPage++; renderTADBPage(); }
    touchStartX = null;
  };
}

// --- EDITOR LOGIC ---

function toggleSection(sectionId) {
  const section = document.getElementById(sectionId);
  if (section.classList.contains("hidden")) {
    section.classList.remove("hidden");
    // If it's the controls panel, ensure it also removes the inline display:none
    if (sectionId === "controls-panel") section.style.display = "grid";
  } else {
    section.classList.add("hidden");
    if (sectionId === "controls-panel") section.style.display = "none";
  }
}

const EXCLUSIVE_PANELS = ['fanart-controls', 'metal-archives-controls', 'tadb-controls', 'controls-panel'];

function toggleExclusive(sectionId) {
  const section = document.getElementById(sectionId);
  if (section.classList.contains('hidden')) {
    // Hide all other panels
    EXCLUSIVE_PANELS.forEach(id => {
      if (id === sectionId) return;
      const el = document.getElementById(id);
      if (!el) return;
      el.classList.add('hidden');
      if (id === 'controls-panel') el.style.display = 'none';
    });
    // Show requested panel
    section.classList.remove('hidden');
    if (sectionId === 'controls-panel') section.style.display = 'grid';
    // Update button active states
    document.querySelectorAll('.section-btn').forEach(btn => {
      const onclick = btn.getAttribute('onclick') || '';
      btn.classList.toggle('active',
        onclick.includes(`toggleExclusive('${sectionId}')`) || onclick.includes(`toggleExclusive("${sectionId}")`));
    });
  } else {
    // Toggle off the active panel
    section.classList.add('hidden');
    if (sectionId === 'controls-panel') section.style.display = 'none';
    document.querySelectorAll('.section-btn').forEach(btn => {
      const onclick = btn.getAttribute('onclick') || '';
      if (onclick.includes(`toggleExclusive('${sectionId}')`) || onclick.includes(`toggleExclusive("${sectionId}")`))
        btn.classList.remove('active');
    });
  }
}

function toggleZoom(checkbox) {
    const zoomSlider = document.getElementById('zoom');
    const previewContainer = document.getElementById('preview-container');
    if (checkbox.checked) {
        zoomSlider.disabled = true;
        previewContainer.style.padding = '22px';
    } else {
        zoomSlider.disabled = false;
        previewContainer.style.padding = '0px';
    }
    updateCSS(); // to reflect the change in preview
}

window.updateCSS = window.updateCSS || function() { console.warn('updateCSS placeholder: real implementation is in preview.js'); };

window.resetFilters = window.resetFilters || function() { console.warn('resetFilters placeholder: real implementation is in preview.js'); };

function convertSvgToPng(svgDataUrl) {
  // Always resolves — either with a PNG data URL (canvas worked) or the original
  // SVG data URL (canvas tainted/failed) so the backend cairosvg can handle it.
  return new Promise((resolve) => {
    const img = new Image();
    const timeout = setTimeout(() => resolve(svgDataUrl), 5000);
    img.onload = () => {
      clearTimeout(timeout);
      try {
        const w = img.naturalWidth > 0 ? img.naturalWidth : 1000;
        const h = img.naturalHeight > 0 ? img.naturalHeight : 1000;
        const canvas = document.createElement('canvas');
        canvas.width = w;
        canvas.height = h;
        canvas.getContext('2d').drawImage(img, 0, 0, w, h);
        resolve(canvas.toDataURL('image/png'));
      } catch (_) {
        resolve(svgDataUrl); // tainted canvas — let backend handle it
      }
    };
    img.onerror = () => { clearTimeout(timeout); resolve(svgDataUrl); };
    img.src = svgDataUrl;
  });
}

window.handleUpload = window.handleUpload || function(input) {
  if (input.files && input.files[0]) {
    const file = input.files[0];
    const reader = new FileReader();
    reader.onload = async (e) => {
      const isSvg = file.type === 'image/svg+xml'
        || file.name.toLowerCase().endsWith('.svg')
        || e.target.result.startsWith('data:image/svg+xml');
      const dataUrl = isSvg ? await convertSvgToPng(e.target.result) : e.target.result;
      selectedUrl = dataUrl;
      document.getElementById("preview-img").src = selectedUrl;
      window.resetFilters && window.resetFilters();
      if (isSvg) {
        const converted = !dataUrl.startsWith('data:image/svg+xml');
        showToast(converted ? 'SVG converted to PNG!' : 'SVG loaded — will convert on save');
      }
    };
    reader.readAsDataURL(file);
  }
};

// --- TEXT GENERATOR ---

function setCase(c) {
  currentCase = c;
  // update UI active state for case buttons
  document.querySelectorAll('.case-btn').forEach(btn => {
    const v = btn.getAttribute('onclick') || '';
    // crude parse: check if the onclick contains the case value
    if (v.includes(`setCase('${c}')`) || v.includes(`setCase("${c}")`)) btn.classList.add('active'); else btn.classList.remove('active');
  });
  previewCustom();
}

async function previewCustom() {
  if (!currentKey) return;
  const res = await fetch("/preview_text", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      rating_key: currentKey,
      font: selectedFont,
      rows: document.getElementById("row-count").value,
      color: selectedColor,
      case: currentCase,
    }),
  });
  const data = await res.json();
  selectedUrl = "data:image/jpeg;base64," + data.image;
  document.getElementById("preview-img").src = selectedUrl;
  resetFilters();
}

async function saveCustom() {
  const res = await fetch("/save_custom", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      rating_key: currentKey,
      font: selectedFont,
      rows: document.getElementById("row-count").value,
      color: selectedColor,
      case: currentCase,
    }),
  });

  const data = await res.json();
  if (data.status === "success") {
    showToast("Custom text logo saved!");
    updateStatus(currentKey, "custom");
    document.getElementById("plex-img").src =
      `/plex_proxy/${currentKey}?t=${Date.now()}`;
  }
}

async function applyMostPopularFanart() {
    const artists = Array.from(selectedArtists);
    if (artists.length === 0) {
        return showToast("No artists selected.", "error");
    }

    showToast(`Applying most popular logo to ${artists.length} artists...`);

    const res = await fetch('/bulk_apply_fanart', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ artist_keys: artists }),
    });

    const data = await res.json();
    if (data.status === 'success') {
        showToast(`Successfully updated ${data.updated_count} artists.`);
        // Refresh status dots for updated artists
        artists.forEach(key => updateStatus(key, 'done'));
    } else {
        showToast("An error occurred during bulk update.", "error");
    }
}

async function bulkToggleStatus() {
    const artists = Array.from(selectedArtists);
    if (artists.length === 0) {
        return showToast("No artists selected.", "error");
    }

    showToast(`Toggling status for ${artists.length} artists...`);

    const res = await fetch('/bulk_toggle_status', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ artist_keys: artists }),
    });

    const data = await res.json();
    if (data.status === 'success') {
        showToast(`Successfully updated ${data.updated_count} artists.`);
        // Refresh status dots for updated artists
        data.updated_artists.forEach(artist => {
            updateStatus(artist.key, artist.new_status);
        });
    } else {
        showToast("An error occurred during bulk update.", "error");
    }
}

// --- SAVING ---

async function save() {
  if (!selectedUrl) return showToast("Select a logo first!", "error");

  const res = await fetch("/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      rating_key: currentKey,
      url: selectedUrl,
      apply_default_size: document.getElementById("apply-default-size").checked,
      invert: document.getElementById("btn-invert").classList.contains("active"),
      contrast: document.getElementById("contrast").value,
      zoom: document.getElementById("zoom").value,
      monochrome: document.getElementById("btn-monochrome").classList.contains("active"),
      tint: selectedImageColor,
      make_white: !!(selectedImageColor && selectedImageColor.toLowerCase && selectedImageColor.toLowerCase() === '#ffffff')
    }),
  });

  const data = await res.json();
  if (data.status === "success") {
    showToast("Saved to Plex!");
    // Refresh local UI state
    updateStatus(currentKey, "done");
    document.getElementById("plex-img").src =
      `/plex_proxy/${currentKey}?t=${Date.now()}`;
  }
}

async function saveCustom() {
  const res = await fetch("/save_custom", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      rating_key: currentKey,
      font: selectedFont,
      rows: document.getElementById("row-count").value,
      color: selectedColor,
      case: currentCase,
    }),
  });

  const data = await res.json();
  if (data.status === "success") {
    showToast("Custom text logo saved!");
    updateStatus(currentKey, "custom");
    document.getElementById("plex-img").src =
      `/plex_proxy/${currentKey}?t=${Date.now()}`;
  }
}

async function toggleStatus(event, key) {
    event.stopPropagation(); // Prevent artist selection
    const res = await fetch(`/toggle_status/${key}`, { method: 'POST' });
    const data = await res.json();
    if (data.status === 'success') {
        updateStatus(key, data.new_status);
        showToast('Status updated!');
    }
}

// --- UTILS ---

function updateStatus(key, status) {
  const item = document.getElementById(`item-${key}`);
  if (item) {
    item.setAttribute("data-status", status);
    const dot = item.querySelector(".status-dot");
    dot.className = `status-dot status-${status}`;
  }
}

function showToast(msg) {
  const t = document.getElementById("toast");
  t.innerText = "✅ " + msg;
  t.style.display = "block";
  setTimeout(() => {
    t.style.display = "none";
  }, 3000);
}

function closeLightbox(e) {
  if (e && e.stopPropagation) e.stopPropagation();
  const lb = document.getElementById('lightbox');
  const lbImg = document.getElementById('lightbox-img');
  if (lb) lb.classList.add('hidden');
  if (lbImg) lbImg.src = '';
}
