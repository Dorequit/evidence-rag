const $ = (selector) => document.querySelector(selector);
const documentsEl = $('#document-list');
const resultsEl = $('#results');
const sourcePanel = $('#source-panel');
const toastEl = $('#toast');
let toastTimer;
let activeDocument = null;
let searchMode = 'extractive';

function setMode(mode) {
  if (mode === 'rag' && $('#rag-mode').disabled) return;
  searchMode = mode;
  for (const [value, id] of [['extractive', '#extractive-mode'], ['rag', '#rag-mode']]) {
    const button = $(id);
    const active = value === mode;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
  }
  $('#mode-pill').classList.toggle('rag', mode === 'rag');
  $('#mode-pill').innerHTML = mode === 'rag'
    ? '<span class="online-dot"></span> API RAG · PAID'
    : '<span class="online-dot"></span> OFFLINE · EXTRACTIVE';
  $('#mode-explainer').textContent = mode === 'rag'
    ? 'Selected passages are sent to OpenAI for a cited answer. API charges apply.'
    : 'Local excerpts only. No document text leaves your computer.';
  $('#search-button').innerHTML = mode === 'rag'
    ? 'Ask <span aria-hidden="true">↗</span>'
    : 'Search <span aria-hidden="true">↗</span>';
}

async function loadCapabilities() {
  const health = await api('/api/health');
  $('#rag-mode').disabled = !health.rag_available;
  $('#rag-mode').title = health.rag_available
    ? 'Use the OpenAI API to answer from retrieved passages'
    : 'Set OPENAI_API_KEY on the server to enable';
}

function toast(message) {
  toastEl.textContent = message;
  toastEl.classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl.classList.remove('visible'), 3200);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

function empty(message, detail) {
  resultsEl.replaceChildren();
  const card = document.createElement('div');
  card.className = 'empty-card';
  card.innerHTML = '<div class="empty-icon">⌕</div>';
  const title = document.createElement('strong');
  title.textContent = message;
  const description = document.createElement('p');
  description.textContent = detail;
  card.append(title, description);
  resultsEl.append(card);
}

async function loadDocuments() {
  const { documents } = await api('/api/documents');
  $('#document-count').textContent = `${documents.length} document${documents.length === 1 ? '' : 's'}`;
  documentsEl.replaceChildren();
  for (const doc of documents) {
    const row = document.createElement('div');
    row.className = 'doc-row';
    const icon = document.createElement('span');
    icon.className = 'doc-icon';
    icon.textContent = doc.kind === 'pdf' ? 'PDF' : doc.kind === 'markdown' ? 'MD' : 'TXT';
    const text = document.createElement('div');
    text.className = 'doc-text';
    const name = document.createElement('span');
    name.className = 'doc-name';
    name.textContent = doc.name;
    name.title = doc.name;
    const meta = document.createElement('span');
    meta.className = 'doc-meta';
    meta.textContent = `${doc.chunks} searchable passage${doc.chunks === 1 ? '' : 's'}`;
    text.append(name, meta);
    const open = document.createElement('button');
    open.className = 'doc-open';
    open.setAttribute('aria-label', `Open ${doc.name}`);
    open.textContent = '↗';
    open.addEventListener('click', () => showDocument(doc.id));
    row.append(icon, text, open);
    documentsEl.append(row);
  }
}

async function showDocument(id, heading = '') {
  try {
    const doc = await api(`/api/documents/${id}`);
    activeDocument = id;
    $('#source-title').textContent = doc.name;
    const body = $('#source-body');
    body.replaceChildren();
    const meta = document.createElement('div');
    meta.className = 'source-meta';
    meta.textContent = `${doc.kind.toUpperCase()} · ${heading || 'Full document'}`;
    const content = document.createElement('div');
    content.className = 'source-content';
    content.textContent = doc.content;
    const actions = document.createElement('div');
    actions.className = 'source-actions';
    const remove = document.createElement('button');
    remove.className = 'delete-button';
    remove.textContent = 'Remove from library';
    remove.addEventListener('click', () => removeDocument(id, doc.name));
    actions.append(remove);
    body.append(meta, content, actions);
    sourcePanel.classList.add('open');
  } catch (error) {
    toast(error.message);
  }
}

async function removeDocument(id, name) {
  if (!window.confirm(`Remove ${name} from this local library?`)) return;
  try {
    await api(`/api/documents/${id}`, { method: 'DELETE' });
    closeSource();
    await loadDocuments();
    empty('Document removed', 'Run another search to refresh the evidence.');
    toast(`${name} removed`);
  } catch (error) {
    toast(error.message);
  }
}

function closeSource() {
  sourcePanel.classList.remove('open');
  activeDocument = null;
}

function renderResults(data) {
  if (data.status === 'empty_query') {
    empty('Add a more specific question', 'Try a term from a document, such as “backup” or “API key”.');
    return;
  }
  if (data.status === 'no_match') {
    empty('No matching passage found', 'Try different keywords or add another document to the library.');
    return;
  }
  resultsEl.replaceChildren();
  const header = document.createElement('div');
  header.className = 'results-head';
  const heading = document.createElement('h2');
  heading.textContent = data.mode === 'rag'
    ? (data.status === 'no_answer' ? 'No grounded answer' : 'Answer with sources')
    : 'Evidence found';
  const count = document.createElement('span');
  count.textContent = `${data.evidence.length} PASSAGE${data.evidence.length === 1 ? '' : 'S'}`;
  header.append(heading, count);
  const notice = document.createElement('div');
  notice.className = 'notice';
  notice.textContent = data.mode === 'rag'
    ? (data.evidence.length
      ? 'The answer mode uses only the passages below. Verify each claim against its source.'
      : 'No relevant passages were found, so no API request was made.')
    : 'These are exact excerpts selected by local keyword retrieval. They are not a generated answer; open a source to verify context.';
  resultsEl.append(header, notice);
  if (data.mode === 'rag') {
    const answer = document.createElement('div');
    answer.className = `answer-card${data.status === 'no_answer' ? ' no-answer' : ''}`;
    const label = document.createElement('div');
    label.className = 'answer-label';
    label.textContent = data.status === 'no_answer' ? 'NOT ENOUGH EVIDENCE' : 'GROUNDED ANSWER';
    const copy = document.createElement('p');
    copy.textContent = data.answer;
    const links = document.createElement('div');
    links.className = 'answer-links';
    for (const id of data.citations) {
      const item = data.evidence.find((passage) => passage.source_id === id);
      if (!item) continue;
      const button = document.createElement('button');
      button.textContent = `${id} · ${item.source}`;
      button.addEventListener('click', () => showDocument(item.document_id, item.heading));
      links.append(button);
    }
    answer.append(label, copy, links);
    resultsEl.append(answer);
  }
  for (const item of data.evidence) {
    const card = document.createElement('article');
    card.className = 'evidence-card';
    const top = document.createElement('div');
    top.className = 'evidence-top';
    const citation = document.createElement('span');
    citation.className = 'citation-number';
    citation.textContent = item.source_id || String(item.citation).padStart(2, '0');
    const source = document.createElement('span');
    source.className = 'evidence-source';
    source.textContent = `${item.source} · ${item.heading}`;
    const page = document.createElement('span');
    page.className = 'evidence-page';
    page.textContent = item.page > 1 ? `p. ${item.page}` : 'SOURCE';
    top.append(citation, source, page);
    const quote = document.createElement('blockquote');
    quote.textContent = `“${item.quote}”`;
    const button = document.createElement('button');
    button.textContent = 'Inspect source →';
    button.addEventListener('click', () => showDocument(item.document_id, item.heading));
    card.append(top, quote, button);
    resultsEl.append(card);
  }
}

async function search(query) {
  const button = $('#search-button');
  button.disabled = true;
  button.textContent = 'Searching…';
  try {
    const data = await api('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, mode: searchMode }),
    });
    renderResults(data);
  } catch (error) {
    empty('Search unavailable', error.message);
  } finally {
    button.disabled = false;
    button.innerHTML = searchMode === 'rag' ? 'Ask <span aria-hidden="true">↗</span>' : 'Search <span aria-hidden="true">↗</span>';
  }
}

async function uploadFiles(files) {
  for (const file of files) {
    if (!/\.(md|txt|pdf)$/i.test(file.name)) {
      toast(`Unsupported file: ${file.name}`);
      continue;
    }
    if (file.size > 5_000_000) {
      toast(`${file.name} exceeds 5 MB`);
      continue;
    }
    try {
      let content, encoding;
      if (/\.pdf$/i.test(file.name)) {
        const bytes = new Uint8Array(await file.arrayBuffer());
        let binary = '';
        for (const byte of bytes) binary += String.fromCharCode(byte);
        content = btoa(binary);
        encoding = 'base64';
      } else {
        content = await file.text();
      }
      const result = await api('/api/documents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: file.name, content, encoding }),
      });
      toast(result.created ? `${file.name} added` : `${file.name} is already in the library`);
    } catch (error) {
      toast(`${file.name}: ${error.message}`);
    }
  }
  await loadDocuments();
  $('#file-input').value = '';
}

$('#search-form').addEventListener('submit', (event) => {
  event.preventDefault();
  search($('#query').value);
});
document.querySelectorAll('[data-query]').forEach((button) => button.addEventListener('click', () => {
  $('#query').value = button.dataset.query;
  search(button.dataset.query);
}));
$('#new-search').addEventListener('click', () => {
  $('#query').value = '';
  closeSource();
  empty('Ready when you are', 'Search the sample runbooks or add your own files to start exploring.');
  $('#query').focus();
});
$('#close-source').addEventListener('click', closeSource);
$('#extractive-mode').addEventListener('click', () => setMode('extractive'));
$('#rag-mode').addEventListener('click', () => setMode('rag'));
$('#file-input').addEventListener('change', (event) => uploadFiles(event.target.files));
const dropzone = $('#upload-zone');
dropzone.addEventListener('dragover', (event) => { event.preventDefault(); dropzone.classList.add('dragover'); });
dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
dropzone.addEventListener('drop', (event) => {
  event.preventDefault();
  dropzone.classList.remove('dragover');
  uploadFiles(event.dataTransfer.files);
});
loadDocuments().catch((error) => toast(error.message));
loadCapabilities().catch((error) => toast(error.message));
