/**
 * game.js — AI Book-to-Game Engine
 * Pure vanilla JavaScript. No external dependencies.
 *
 * Responsibilities:
 *  - Game screen: load state, send commands, update all UI regions
 *  - Library screen: load saved games, Gutenberg search/pagination, file upload
 *  - Shared utilities: toast notifications, markdown mini-renderer, fetch wrapper
 */

/* ═══════════════════════════════════════════════════════════════
   SHARED UTILITIES
   ═══════════════════════════════════════════════════════════════ */

/**
 * Show a brief toast notification at the bottom-right of the screen.
 * @param {string} message
 * @param {'info'|'error'} [type='info']
 * @param {number} [duration=4000] ms
 */
function showToast(message, type = 'info', duration = 4000) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = 'toast' + (type === 'error' ? ' toast-error' : '');
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.add('fade-out');
    setTimeout(() => toast.remove(), 450);
  }, duration);
}

/**
 * Minimal markdown-to-HTML converter for game output lines.
 * Handles **bold**, _italic_, and \n → <br>.
 * @param {string} text
 * @returns {string} Safe HTML string
 */
function renderMarkdown(text) {
  // Escape HTML entities first to prevent XSS
  const escaped = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

  return escaped
    .replace(/\*\*(.+?)\*\*/g,  '<strong>$1</strong>')
    .replace(/_(.+?)_/g,         '<em>$1</em>')
    .replace(/\n/g,              '<br>');
}

/**
 * Generic fetch wrapper with error handling.
 * @param {string} url
 * @param {RequestInit} [options={}]
 * @returns {Promise<{ok:boolean, data:any, error:string|null}>}
 */
async function apiFetch(url, options = {}) {
  try {
    const resp = await fetch(url, {
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      return { ok: false, data: null, error: data.error || data.message || `HTTP ${resp.status}` };
    }
    return { ok: true, data, error: null };
  } catch (err) {
    return { ok: false, data: null, error: err.message };
  }
}

/* ═══════════════════════════════════════════════════════════════
   GAME SCREEN
   ═══════════════════════════════════════════════════════════════ */

/** book_id read from body[data-book-id], set by the Jinja2 template */
let BOOK_ID = null;
let isLoading = false;

/* ── DOM refs (may be null on non-game pages) ─────────────────── */
const gameOutput     = () => document.getElementById('game-output');
const gameInput      = () => document.getElementById('game-input');
const sendBtn        = () => document.getElementById('send-btn');
const locationName   = () => document.getElementById('location-name');
const exitsList      = () => document.getElementById('exits-list');
const charactersList = () => document.getElementById('characters-list');
const itemsList      = () => document.getElementById('items-list');
const inventoryList  = () => document.getElementById('inventory-list');
const scoreValue     = () => document.getElementById('score-value');
const moveCount      = () => document.getElementById('move-count');
const sceneImage     = () => document.getElementById('scene-image');
const scenePlaceholder = () => document.getElementById('scene-placeholder');
const imageSpinner   = () => document.getElementById('image-spinner');
const breadcrumbTitle = () => document.getElementById('breadcrumb-title');

/**
 * Append a line to the game output log.
 * @param {string} text - May contain markdown and \n
 * @param {'normal'|'system'|'action'|'error'} [type='normal']
 */
function addOutput(text, type = 'normal') {
  const out = gameOutput();
  if (!out) return;
  const p = document.createElement('p');
  p.className = 'output-line' + (type !== 'normal' ? ` output-${type}` : '');
  p.innerHTML = renderMarkdown(text);
  out.appendChild(p);
  // Auto-scroll to the bottom
  out.scrollTop = out.scrollHeight;
}

/**
 * Set the loading state (disables input, shows visual feedback).
 * @param {boolean} loading
 */
function setLoadingState(loading) {
  isLoading = loading;
  const inp = gameInput();
  const btn = sendBtn();
  if (inp) {
    inp.disabled = loading;
    if (!loading) {
      inp.focus();
    }
  }
  if (btn) {
    btn.disabled = loading;
    btn.textContent = loading ? '…' : 'Send';
  }
}

/**
 * Update all game UI regions from a state object returned by the API.
 * @param {Object} data - Game state response
 */
function updateUI(data) {
  /* Location name */
  const locEl = locationName();
  if (locEl && data.location) locEl.textContent = data.location;

  /* Breadcrumb title */
  const bc = breadcrumbTitle();
  if (bc && data.book_title) bc.textContent = data.book_title;

  /* Minimap */
  if (data.minimap) {
    const mm = data.minimap;
    const dirs = {
      'north': 'mm-n', 'south': 'mm-s', 'east': 'mm-e', 'west': 'mm-w'
    };
    
    // Clear all directional cells
    for (const [dir, id] of Object.entries(dirs)) {
      const cell = document.getElementById(id);
      if (cell) {
        cell.className = `mm-cell mm-${dir.charAt(0)}`;
        cell.textContent = '';
        if (mm[dir] && mm[dir].exists) {
          cell.textContent = mm[dir].name;
          cell.classList.add(mm[dir].visited ? 'visited-room' : 'unvisited-room');
          // Make it clickable if visited
          if (mm[dir].visited) {
            cell.style.cursor = 'pointer';
            cell.onclick = () => sendCommand(`go ${dir}`);
          } else {
            cell.style.cursor = 'default';
            cell.onclick = null;
          }
        }
      }
    }
    
    // Center cell
    const center = document.getElementById('mm-c');
    if (center) {
      center.className = 'mm-cell mm-c active-room';
      center.innerHTML = '<span class="mm-marker">★</span>';
    }
    
    // Vertical badges
    const vert = document.getElementById('minimap-vertical');
    if (vert) {
      vert.innerHTML = '';
      if (mm.vertical && mm.vertical.length > 0) {
        mm.vertical.forEach(v => {
          const badge = document.createElement('span');
          badge.className = 'mm-vert-badge';
          badge.textContent = v.toUpperCase();
          badge.style.cursor = 'pointer';
          badge.onclick = () => sendCommand(`go ${v}`);
          vert.appendChild(badge);
        });
      }
    }
  }

  /* Exits */
  const exitsEl = exitsList();
  if (exitsEl) {
    exitsEl.innerHTML = '';
    const exits = data.exits || [];
    if (exits.length === 0) {
      exitsEl.innerHTML = '<span class="none-item">None</span>';
    } else {
      exits.forEach(dir => {
        const btn = document.createElement('button');
        btn.className = 'exit-btn';
        btn.textContent = dir;
        btn.setAttribute('aria-label', `Go ${dir}`);
        btn.addEventListener('click', () => sendCommand(`go ${dir}`));
        exitsEl.appendChild(btn);
      });
    }
  }

  /* Characters present */
  const charsEl = charactersList();
  if (charsEl) {
    charsEl.innerHTML = '';
    const chars = data.characters || [];
    if (chars.length === 0) {
      charsEl.innerHTML = '<li class="detail-item none-item">None</li>';
    } else {
      chars.forEach(c => {
        const li = document.createElement('li');
        li.className = 'detail-item';
        li.textContent = c;
        charsEl.appendChild(li);
      });
    }
  }

  /* Items in location */
  const itemsEl = itemsList();
  if (itemsEl) {
    itemsEl.innerHTML = '';
    const items = data.items_here || [];
    if (items.length === 0) {
      itemsEl.innerHTML = '<li class="detail-item none-item">None</li>';
    } else {
      items.forEach(item => {
        const li = document.createElement('li');
        li.className = 'detail-item';
        li.textContent = item;
        itemsEl.appendChild(li);
      });
    }
  }

  /* Inventory */
  const invEl = inventoryList();
  if (invEl) {
    invEl.innerHTML = '';
    const inv = data.inventory || [];
    if (inv.length === 0) {
      invEl.innerHTML = '<span class="inventory-item none-item">Empty</span>';
    } else {
      inv.forEach(item => {
        const span = document.createElement('span');
        span.className = 'inventory-item';
        span.textContent = item;
        invEl.appendChild(span);
      });
    }
  }

  /* Score & moves */
  const scoreEl = scoreValue();
  const movesEl = moveCount();
  if (scoreEl) scoreEl.textContent = data.score  ?? 0;
  if (movesEl) movesEl.textContent = data.moves  ?? 0;

  /* Scene image */
  if (data.image_url) {
    const img   = sceneImage();
    const ph    = scenePlaceholder();
    const spin  = imageSpinner();
    if (img) {
      if (spin) spin.classList.add('hidden');
      img.onload = () => {
        img.classList.remove('hidden');
        if (ph) ph.classList.add('hidden');
      };
      img.onerror = () => {
        img.classList.add('hidden');
        if (ph) ph.classList.remove('hidden');
      };
      img.src = data.image_url;
    }
  } else if (data.image_generating) {
    /* Image is being generated in the background */
    const spin = imageSpinner();
    if (spin) spin.classList.remove('hidden');
  }

  /* Narrative / description text */
  if (data.text) addOutput(data.text);
}

/**
 * Send a command to the game API and update the UI.
 * @param {string} input - Raw command string
 */
async function sendCommand(input) {
  const cmd = (input || '').trim();
  if (!cmd || isLoading) return;

  const inp = gameInput();
  if (inp) inp.value = '';

  /* Echo the player's command */
  addOutput(`> ${cmd}`, 'action');

  setLoadingState(true);

  const { ok, data, error } = await apiFetch(`/api/game/${BOOK_ID}/action`, {
    method: 'POST',
    body: JSON.stringify({ command: cmd }),
  });

  setLoadingState(false);

  if (!ok) {
    addOutput(`Error: ${error}`, 'error');
    showToast(error, 'error');
    return;
  }

  updateUI(data);
}

/**
 * Load the initial game state on page load.
 */
async function loadInitialState() {
  if (!BOOK_ID) return;
  addOutput('Loading game…', 'system');

  const { ok, data, error } = await apiFetch(`/api/game/${BOOK_ID}/state`);
  if (!ok) {
    addOutput(`Failed to load game: ${error}`, 'error');
    showToast('Failed to load game: ' + error, 'error');
    return;
  }

  /* Clear the "Loading game…" line */
  const out = gameOutput();
  if (out) out.innerHTML = '';

  updateUI(data);
}

/* ── Input event bindings (game screen) ─────────────────────── */
function initGameScreen() {
  const inp = gameInput();
  const btn = sendBtn();

  if (!inp || !btn) return; // not on game page

  inp.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendCommand(inp.value);
    }
  });

  btn.addEventListener('click', () => sendCommand(gameInput().value));
}

/* ═══════════════════════════════════════════════════════════════
   LIBRARY SCREEN
   ═══════════════════════════════════════════════════════════════ */

/** Gutenberg search pagination state */
let gutenbergPage  = 1;
let gutenbergQuery = '';
let gutenbergTopic = '';
let gutenbergTotal = 0;

/**
 * Fetch and render the user's saved library of games.
 */
async function loadLibrary() {
  const listEl = document.getElementById('my-games-list');
  if (!listEl) return;

  listEl.innerHTML = '<p class="placeholder-text">Loading…</p>';

  const { ok, data, error } = await apiFetch('/api/library');
  if (!ok) {
    listEl.innerHTML = `<p class="test-fail">Failed to load library: ${error}</p>`;
    return;
  }

  const games = data.games || [];
  if (games.length === 0) {
    listEl.innerHTML = '<p class="placeholder-text">No games yet. Load a book to get started!</p>';
    return;
  }

  listEl.innerHTML = '';
    games.forEach(game => {
      const card = document.createElement('div');
      card.className = 'game-card';
      card.innerHTML = `
        <div class="game-card-title">${escapeHtml(game.title || 'Untitled')}</div>
        <div class="game-card-author">${escapeHtml(game.author || '')}</div>
        <div class="game-card-meta">Last played: ${escapeHtml(game.last_played || 'Never')}</div>
        <div style="display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap;">
          <a class="btn btn-primary" href="/game/${encodeURIComponent(game.id)}">▶ Play</a>
          <button class="btn btn-secondary restart-btn" data-id="${escapeHtml(game.id)}">↺ Restart</button>
          <button class="btn btn-danger delete-btn" data-id="${escapeHtml(game.id)}">🗑 Delete</button>
        </div>
      `;
      
      const restartBtn = card.querySelector('.restart-btn');
      restartBtn.addEventListener('click', async () => {
        if (!confirm(`Are you sure you want to restart "${game.title}"? Your saved progress will be lost and you will start over from the beginning.`)) return;
        const res = await fetch(`/api/library/${encodeURIComponent(game.id)}/restart`, { method: 'POST' });
        if (res.ok) {
          showToast('Game restarted! Click play to start fresh.');
          loadLibrary();
        } else {
          showToast('Failed to restart game.', 'error');
        }
      });
      
      const deleteBtn = card.querySelector('.delete-btn');
      deleteBtn.addEventListener('click', async () => {
        if (!confirm(`Are you sure you want to permanently delete "${game.title}"? This cannot be undone.`)) return;
        const res = await fetch(`/api/library/${encodeURIComponent(game.id)}`, { method: 'DELETE' });
        if (res.ok) {
          showToast('Game deleted.');
          loadLibrary();
        } else {
          showToast('Failed to delete game.', 'error');
        }
      });
      
      listEl.appendChild(card);
    });
}

/**
 * Search Project Gutenberg via the backend API.
 * @param {string} query
 * @param {string} topic
 * @param {number} [page=1]
 */
async function gutenbergSearch(query, topic, page = 1) {
  const resultsEl    = document.getElementById('gutenberg-results');
  const spinner      = document.getElementById('gutenberg-spinner');
  const paginationEl = document.getElementById('gutenberg-pagination');
  const pageInfo     = document.getElementById('gutenberg-page-info');
  const prevBtn      = document.getElementById('gutenberg-prev');
  const nextBtn      = document.getElementById('gutenberg-next');

  if (!resultsEl) return;

  gutenbergQuery = query;
  gutenbergTopic = topic;
  gutenbergPage  = page;

  /* Show spinner, hide previous results */
  if (spinner)      spinner.classList.remove('hidden');
  if (paginationEl) paginationEl.classList.add('hidden');
  resultsEl.innerHTML = '';

  const params = new URLSearchParams({ q: query, topic, page: String(page) });
  const { ok, data, error } = await apiFetch(`/api/gutenberg/search?${params}`);

  if (spinner) spinner.classList.add('hidden');

  if (!ok) {
    resultsEl.innerHTML = `<p class="test-fail">Search error: ${error}</p>`;
    return;
  }

  const books = data.results || [];
  gutenbergTotal = data.count || 0;

  if (books.length === 0) {
    resultsEl.innerHTML = '<p class="placeholder-text">No results found.</p>';
    return;
  }

  books.forEach(book => {
    const authorStr = (book.authors || []).map(a => a.name).join(', ');
    const card = document.createElement('div');
    card.className = 'game-card';
    card.innerHTML = `
      <div class="game-card-title">${escapeHtml(book.title || 'Untitled')}</div>
      <div class="game-card-author">${escapeHtml(authorStr)}</div>
      <div class="game-card-meta">Downloads: ${escapeHtml(String(book.download_count || 0))}</div>
      <button class="btn btn-primary" data-gutenberg-id="${escapeHtml(String(book.id))}">&#9889; Generate Game</button>
    `;
    const btn = card.querySelector('button');
    btn.addEventListener('click', () => loadGutenbergBook(book.id, btn));
    resultsEl.appendChild(card);
  });

  /* Pagination */
  if (paginationEl) {
    const totalPages = Math.ceil(gutenbergTotal / (data.page_size || 20));
    if (totalPages > 1) {
      paginationEl.classList.remove('hidden');
      if (pageInfo) pageInfo.textContent = `Page ${page} of ${totalPages}`;
      if (prevBtn)  prevBtn.disabled  = (page <= 1);
      if (nextBtn)  nextBtn.disabled  = (page >= totalPages);
    }
  }
}

async function pollJobStatus(jobId, onProgress) {
  while (true) {
    const { ok, data, error } = await apiFetch(`/api/library/status/${jobId}`);
    if (!ok) throw new Error(error || 'Failed to check status');
    
    if (data.status === 'done') {
      return data; // contains book_id
    }
    if (data.status === 'error') {
      throw new Error(data.error || 'Generation failed on server');
    }
    
    // Status is 'generating'
    if (onProgress && data.message) {
      onProgress(data);
    }
    
    // wait 2 seconds before next poll
    await new Promise(r => setTimeout(r, 2000));
  }
}

/**
 * Trigger game generation from a Project Gutenberg book ID.
 * Shows a full-screen progress overlay while generation runs.
 * @param {number|string} bookId
 * @param {HTMLButtonElement} [triggerBtn]
 */
async function loadGutenbergBook(bookId, triggerBtn) {
  const overlay      = document.getElementById('generation-overlay');
  const progressEl   = document.getElementById('overlay-progress');
  const messageEl    = document.getElementById('overlay-message');

  if (triggerBtn) {
    triggerBtn.disabled = true;
    triggerBtn.textContent = 'Loading…';
  }

  if (overlay) overlay.classList.remove('hidden');

  const { ok, data, error } = await apiFetch(`/api/gutenberg/load/${bookId}`, { method: 'POST' });

  if (!ok) {
    if (overlay) overlay.classList.add('hidden');
    if (triggerBtn) {
      triggerBtn.disabled = false;
      triggerBtn.textContent = '⚡ Generate Game';
    }
    showToast('Failed to start generation: ' + error, 'error');
    return;
  }
  
  if (messageEl) messageEl.textContent = 'Starting generation...';
  
  try {
    const finalData = await pollJobStatus(data.job_id, (status) => {
      if (messageEl) messageEl.textContent = status.message;
      if (progressEl && status.total > 0) {
        progressEl.style.width = Math.round((status.progress / status.total) * 100) + '%';
      } else if (progressEl) {
        // fake progress bouncing
        const cur = parseFloat(progressEl.style.width || '0');
        progressEl.style.width = (cur + 2 > 95 ? 95 : cur + 2) + '%';
      }
    });
    
    if (progressEl) progressEl.style.width = '100%';
    if (messageEl)  messageEl.textContent  = 'Done! Starting game…';
    
    setTimeout(() => {
      window.location.href = `/game/${encodeURIComponent(finalData.book_id)}`;
    }, 500);
    
  } catch (err) {
    if (overlay) overlay.classList.add('hidden');
    if (triggerBtn) {
      triggerBtn.disabled = false;
      triggerBtn.textContent = '⚡ Generate Game';
    }
    showToast('Generation failed: ' + err.message, 'error');
  }
}

const gutenbergLoad = loadGutenbergBook;

/**
 * Upload a local book file (PDF, EPUB, or TXT) for game generation.
 * @param {File} file
 */
async function uploadFile(file) {
  const progressWrap = document.getElementById('upload-progress-wrap');
  const progressBar  = document.getElementById('upload-progress');
  const statusEl     = document.getElementById('upload-status');
  const overlay      = document.getElementById('generation-overlay');
  const messageEl    = document.getElementById('overlay-message');
  const overlayProg  = document.getElementById('overlay-progress');
  const loadBtn      = document.getElementById('load-book-btn');

  if (loadBtn)      loadBtn.disabled = true;
  if (progressWrap) progressWrap.classList.remove('hidden');
  if (statusEl)     statusEl.textContent = 'Uploading…';
  if (progressBar)  progressBar.style.width = '0%';

  const formData = new FormData();
  formData.append('book', file);

  try {
    /* Use XMLHttpRequest to get upload progress events */
    const result = await new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();

      xhr.upload.addEventListener('progress', e => {
        if (e.lengthComputable) {
          const pct = Math.round((e.loaded / e.total) * 100);
          if (progressBar) progressBar.style.width = pct + '%';
          if (statusEl)    statusEl.textContent = `Uploading… ${pct}%`;
        }
      });

      xhr.addEventListener('load', () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(JSON.parse(xhr.responseText));
        } else {
          let err = `HTTP ${xhr.status}`;
          try { err = JSON.parse(xhr.responseText).error || err; } catch {}
          reject(new Error(err));
        }
      });

      xhr.addEventListener('error',  () => reject(new Error('Network error')));
      xhr.addEventListener('abort',  () => reject(new Error('Upload aborted')));

      xhr.open('POST', '/api/library/upload');
      xhr.send(formData);
    });

    if (statusEl) statusEl.textContent = 'Upload complete.';
    
    // Now poll for the generation task
    if (overlay)   overlay.classList.remove('hidden');
    if (messageEl) messageEl.textContent = 'Starting generation...';
    
    const finalData = await pollJobStatus(result.job_id, (status) => {
      if (messageEl) messageEl.textContent = status.message;
      if (overlayProg && status.total > 0) {
        overlayProg.style.width = Math.round((status.progress / status.total) * 100) + '%';
      } else if (overlayProg) {
        const cur = parseFloat(overlayProg.style.width || '0');
        overlayProg.style.width = (cur + 2 > 95 ? 95 : cur + 2) + '%';
      }
    });

    if (overlayProg) overlayProg.style.width = '100%';
    if (messageEl)   messageEl.textContent = 'Done! Starting game…';
    
    setTimeout(() => {
      window.location.href = `/game/${encodeURIComponent(finalData.book_id)}`;
    }, 500);

  } catch (err) {
    if (progressWrap) progressWrap.classList.add('hidden');
    if (loadBtn)      loadBtn.disabled = false;
    if (overlay)      overlay.classList.add('hidden');
    showToast('Upload failed: ' + err.message, 'error');
  }
}

/* ── Library screen event bindings ─────────────────────────── */
function initLibraryScreen() {
  /* Search button */
  const searchBtn = document.getElementById('gutenberg-search-btn');
  if (searchBtn) {
    searchBtn.addEventListener('click', () => {
      const q  = (document.getElementById('gutenberg-query')?.value || '').trim();
      const t  = document.getElementById('gutenberg-topic')?.value || '';
      gutenbergSearch(q, t, 1);
    });
  }

  /* Search on Enter key in query field */
  const queryInput = document.getElementById('gutenberg-query');
  if (queryInput) {
    queryInput.addEventListener('keydown', e => {
      if (e.key === 'Enter') {
        const t = document.getElementById('gutenberg-topic')?.value || '';
        gutenbergSearch(queryInput.value.trim(), t, 1);
      }
    });
  }

  /* Pagination */
  document.getElementById('gutenberg-prev')?.addEventListener('click', () =>
    gutenbergSearch(gutenbergQuery, gutenbergTopic, gutenbergPage - 1));
  document.getElementById('gutenberg-next')?.addEventListener('click', () =>
    gutenbergSearch(gutenbergQuery, gutenbergTopic, gutenbergPage + 1));

  /* File input / drag-and-drop */
  const dropZone  = document.getElementById('drop-zone');
  const fileInput = document.getElementById('book-file-input');
  const loadBtn   = document.getElementById('load-book-btn');
  const fileLabel = document.getElementById('selected-file-name');

  let selectedFile = null;

  function onFileSelected(file) {
    selectedFile = file;
    if (fileLabel) {
      fileLabel.textContent = `Selected: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
      fileLabel.classList.remove('hidden');
    }
    if (loadBtn) loadBtn.disabled = false;
  }

  if (dropZone) {
    /* Click to open file picker */
    dropZone.addEventListener('click', () => fileInput && fileInput.click());
    dropZone.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') fileInput && fileInput.click();
    });

    /* Drag events */
    dropZone.addEventListener('dragover', e => {
      e.preventDefault();
      dropZone.classList.add('dragover');
    });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
    dropZone.addEventListener('drop', e => {
      e.preventDefault();
      dropZone.classList.remove('dragover');
      const file = e.dataTransfer?.files?.[0];
      if (file) onFileSelected(file);
    });
  }

  if (fileInput) {
    fileInput.addEventListener('change', () => {
      const file = fileInput.files?.[0];
      if (file) onFileSelected(file);
    });
  }

  if (loadBtn) {
    loadBtn.addEventListener('click', () => {
      if (selectedFile) uploadFile(selectedFile);
    });
  }

  /* Load the saved library */
  loadLibrary();
}

/* ═══════════════════════════════════════════════════════════════
   HELPERS
   ═══════════════════════════════════════════════════════════════ */

/** Escape HTML for safe insertion into innerHTML */
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/* ═══════════════════════════════════════════════════════════════
   BOOTSTRAP — runs on every page after DOM is ready
   ═══════════════════════════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', () => {
  /* Read book_id from the body data attribute (set by Jinja2 base.html) */
  BOOK_ID = document.body.dataset.bookId || null;

  /* Determine which page we are on and initialise accordingly */
  const onGamePage    = !!document.getElementById('game-output');
  const onLibraryPage = !!document.getElementById('my-games-list');

  if (onGamePage && BOOK_ID) {
    initGameScreen();
    loadInitialState();
  }

  if (onLibraryPage) {
    initLibraryScreen();
  }
});