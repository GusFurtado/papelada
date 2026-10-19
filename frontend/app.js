(function () {
  var t = I18N.t;

  function icon(name) {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
      'stroke-linejoin="round" aria-hidden="true">' + (ICON_PATHS[name] || ICON_PATHS.folder) + '</svg>';
  }

  function $(id) {
    return document.getElementById(id);
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function iconButton(name, label, onClick) {
    var btn = el('button');
    btn.type = 'button';
    btn.title = label;
    btn.setAttribute('aria-label', label);
    btn.innerHTML = icon(name);
    btn.addEventListener('click', onClick);
    return btn;
  }

  // --- elements ---------------------------------------------------------------

  var sectionTabs = $('sectionTabs');
  var tagFilter = $('tagFilter');
  var welcome = $('welcome');
  var emptyList = $('emptyList');
  var documentList = $('documentList');
  var selectModeBtn = $('selectModeBtn');
  var selectionBar = $('selectionBar');
  var selectionCount = $('selectionCount');

  var documentDialog = $('documentDialog');
  var titleInput = $('titleInput');
  var dateInput = $('dateInput');
  var sectionSelect = $('sectionSelect');
  var formTags = $('formTags');
  var newTagInput = $('newTagInput');
  var newPagesField = $('newPagesField');
  var pendingPagesEl = $('pendingPages');
  var editPagesField = $('editPagesField');
  var editPagesEl = $('editPages');
  var cameraInput = $('cameraInput');
  var filesInput = $('filesInput');
  var documentStatus = $('documentStatus');

  var viewDialog = $('viewDialog');
  var viewPages = $('viewPages');

  var downloadMenu = $('downloadMenu');

  var editorDialog = $('editorDialog');
  var editorStage = $('editorStage');
  var editorImage = $('editorImage');
  var editorStatus = $('editorStatus');
  var formatSelect = $('formatSelect');

  var sectionDialog = $('sectionDialog');
  var sectionNameInput = $('sectionNameInput');
  var iconGrid = $('iconGrid');
  var sectionStatus = $('sectionStatus');

  var manageDialog = $('manageDialog');
  var nameDialog = $('nameDialog');
  var nameInput = $('nameInput');
  var nameStatus = $('nameStatus');

  var securityDialog = $('securityDialog');
  var securityStatus = $('securityStatus');
  var toggleEncryptionBtn = $('toggleEncryption');

  var confirmDialog = $('confirmDialog');

  var loginDialog = $('loginDialog');
  var usernameInput = $('usernameInput');
  var passwordInput = $('passwordInput');
  var loginStatus = $('loginStatus');

  I18N.apply(document);
  document.querySelector('#logoutBtn .btn-icon').innerHTML = icon('log-out');
  document.querySelector('#securityBtn .btn-icon').innerHTML = icon('lock-open');
  document.querySelector('#manageBtn .btn-icon').innerHTML = icon('settings');
  document.querySelector('#selectModeBtn .btn-icon').innerHTML = icon('square-check-big');
  document.querySelector('#uploadBtn .btn-icon').innerHTML = icon('plus');
  document.querySelector('#welcomeNewSection .btn-icon').innerHTML = icon('plus');
  document.querySelector('#cancelSelection .btn-icon').innerHTML = icon('x');
  document.querySelector('#downloadSelected .btn-icon').innerHTML = icon('download');
  document.querySelector('#takePhotoBtn .btn-icon').innerHTML = icon('camera');
  document.querySelector('#addFilesBtn .btn-icon').innerHTML = icon('file');
  document.querySelector('#manageNewSection .btn-icon').innerHTML = icon('plus');
  document.querySelector('#manageNewTag .btn-icon').innerHTML = icon('plus');
  document.querySelector('#scanBtn .btn-icon').innerHTML = icon('refresh-cw');
  $('addTagBtn').innerHTML = icon('plus');
  $('editDocumentBtn').innerHTML = icon('pencil');
  $('deleteDocumentBtn').innerHTML = icon('trash');
  $('closeViewBtn').innerHTML = icon('x');
  $('downloadDocumentBtn').innerHTML = icon('download');
  document.querySelector('#downloadFilesBtn .btn-icon').innerHTML = icon('file-archive');
  document.querySelector('#downloadPdfBtn .btn-icon').innerHTML = icon('file-down');
  $('editorPrev').innerHTML = icon('chevron-left');
  $('editorNext').innerHTML = icon('chevron-right');
  $('rotateLeftBtn').innerHTML = icon('rotate-ccw');
  $('rotateRightBtn').innerHTML = icon('rotate-cw');
  document.querySelector('#scanFilterBtn .btn-icon').innerHTML = icon('scan-line');
  document.querySelector('#reduceBtn .btn-icon').innerHTML = icon('shrink');
  document.querySelector('#restorePageBtn .btn-icon').innerHTML = icon('undo-2');

  // --- state ------------------------------------------------------------------

  var sections = [];
  var tags = [];
  var documents = [];  // every document of the active section; the tag filter is applied when rendering
  var activeSectionId = null;
  var activeTagId = null;
  var encrypted = false;
  var encryptionAvailable = false;
  var uploadSettings = { strip_metadata: true, reduce_uploads: false };

  var viewingDoc = null;
  var editingDoc = null;
  var formTagIds = [];
  var pendingFiles = [];
  var pagesChangedDuringEdit = false;
  var selectMode = false;
  var selectedIds = [];
  var cropper = null;
  var editor = null;  // the page editor's state while it's open; see openPageEditor
  var editingSection = null;
  var chosenIcon = 'folder';
  var nameDialogSave = null;

  var ACTIVE_SECTION_KEY = 'papelada.activeSection';

  function remember(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { /* storage unavailable: just don't remember */ }
  }

  function recall(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }

  // --- helpers ------------------------------------------------------------------

  function api(method, url, body) {
    var options = { method: method };
    if (body instanceof FormData) {
      options.body = body;
    } else if (body !== undefined) {
      options.headers = { 'Content-Type': 'application/json' };
      options.body = JSON.stringify(body);
    }
    return fetch(url, options).then(function (res) {
      if (res.ok) return res.json();
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (res.status === 401 && data.detail === 'login_required') showLogin();
        var err = new Error(typeof data.detail === 'string' ? data.detail : 'request failed');
        err.code = typeof data.detail === 'string' ? data.detail : null;
        err.info = data;
        throw err;
      });
    });
  }

  function errorMessage(err) {
    var key = 'errors.' + (err && err.code);
    return I18N.has(key) ? t(key, err.info) : t('errors.generic');
  }

  function pageUrl(doc, page, what) {
    return 'api/documents/' + doc.id + '/pages/' + page.id + '/' + what + '?v=' + page.rev;
  }

  function contentUrl(doc, page) {
    return pageUrl(doc, page, 'content');
  }

  // Server-side thumbnails exist for every page the editor can open (page.editable).
  function thumbnailUrl(doc, page) {
    return pageUrl(doc, page, 'thumbnail');
  }

  function extLabel(page) {
    return (page.ext || '').slice(1).toUpperCase();
  }

  function todayIso() {
    var d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }

  var dateFormat = new Intl.DateTimeFormat(navigator.languages && navigator.languages.length ? navigator.languages : undefined,
    { dateStyle: 'medium' });

  function formatDate(iso) {
    var parts = (iso || '').split('-');
    if (parts.length !== 3) return iso || '';
    return dateFormat.format(new Date(+parts[0], +parts[1] - 1, +parts[2]));
  }

  function findById(list, id) {
    for (var i = 0; i < list.length; i++) {
      if (list[i].id === id) return list[i];
    }
    return null;
  }

  function isImage(page) {
    return page.mime.indexOf('image/') === 0 && page.mime !== 'image/svg+xml';
  }

  function isPreviewable(page) {
    return ['image/jpeg', 'image/png', 'image/webp', 'image/gif', 'image/avif', 'application/pdf'].indexOf(page.mime) !== -1;
  }

  // For dialogs with nothing typed in them to lose; forms close with Cancel only.
  // Backdrop clicks are dispatched to the dialog element itself, so check the
  // position too; a drag that merely ends outside the box doesn't count.
  function closeOnBackdropClick(dialog, canClose) {
    var pressedOutside = false;
    function isOutside(ev) {
      var box = dialog.getBoundingClientRect();
      return ev.target === dialog &&
        (ev.clientX < box.left || ev.clientX > box.right || ev.clientY < box.top || ev.clientY > box.bottom);
    }
    dialog.addEventListener('pointerdown', function (ev) { pressedOutside = isOutside(ev); });
    dialog.addEventListener('click', function (ev) {
      if (pressedOutside && isOutside(ev) && (!canClose || canClose())) dialog.close();
    });
  }

  function confirmAction(message, confirmLabel) {
    return new Promise(function (resolve) {
      $('confirmMessage').textContent = message;
      $('confirmOk').textContent = confirmLabel || t('delete');
      $('confirmOk').onclick = function () { confirmDialog.close(); resolve(true); };
      $('confirmCancel').onclick = function () { confirmDialog.close(); resolve(false); };
      confirmDialog.showModal();
    });
  }

  // --- loading -------------------------------------------------------------------

  function loadSections() {
    return api('GET', 'api/sections').then(function (list) {
      sections = list;
      if (!findById(sections, activeSectionId)) {
        var remembered = recall(ACTIVE_SECTION_KEY);
        activeSectionId = findById(sections, remembered) ? remembered : (sections[0] ? sections[0].id : null);
      }
      renderSections();
    });
  }

  function loadTags() {
    return api('GET', 'api/tags').then(function (list) {
      tags = list;
      if (activeTagId && !findById(tags, activeTagId)) activeTagId = null;
    });
  }

  function loadDocuments() {
    if (!activeSectionId) {
      documents = [];
      renderDocuments();
      return Promise.resolve();
    }
    return api('GET', 'api/documents?section=' + encodeURIComponent(activeSectionId)).then(function (list) {
      documents = list;
      renderDocuments();
    });
  }

  function loadSettings() {
    return api('GET', 'api/settings').then(function (settings) {
      encrypted = settings.encrypted;
      encryptionAvailable = settings.encryption_available;
      uploadSettings = { strip_metadata: settings.strip_metadata, reduce_uploads: settings.reduce_uploads };
      renderSecurity();
    });
  }

  function refresh() {
    return Promise.all([loadSections(), loadTags()]).then(loadDocuments).then(function () {
      if (manageDialog.open) renderManage();
    });
  }

  // --- main view -------------------------------------------------------------------

  function setActiveSection(sectionId) {
    activeSectionId = sectionId;
    activeTagId = null;
    remember(ACTIVE_SECTION_KEY, sectionId);
    exitSelectMode();
  }

  function selectSection(sectionId) {
    setActiveSection(sectionId);
    renderSections();
    loadDocuments();
  }

  function renderSections() {
    sectionTabs.innerHTML = '';
    var hasSections = sections.length > 0;
    welcome.hidden = hasSections;
    sectionTabs.hidden = !hasSections;
    selectModeBtn.hidden = !hasSections;

    sections.forEach(function (section) {
      var tab = el('button', section.id === activeSectionId ? 'active' : '');
      tab.type = 'button';
      tab.innerHTML = icon(section.icon);
      tab.appendChild(el('span', null, section.name));
      tab.addEventListener('click', function () { selectSection(section.id); });
      sectionTabs.appendChild(tab);
    });
    var add = iconButton('plus', t('newSection'), function () { openSectionDialog(null); });
    add.className = 'add-section';
    sectionTabs.appendChild(add);

    var activeTab = sectionTabs.querySelector('.active');
    if (activeTab && activeTab.scrollIntoView) activeTab.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }

  function renderTagFilter() {
    tagFilter.innerHTML = '';
    var used = {};
    documents.forEach(function (doc) {
      doc.tags.forEach(function (tagId) { used[tagId] = true; });
    });
    var usedTags = tags.filter(function (tag) { return used[tag.id]; });
    tagFilter.hidden = !usedTags.length;
    if (!usedTags.length) return;

    function addChip(tagId, label) {
      var chip = el('button', activeTagId === tagId ? 'active' : '', label);
      chip.type = 'button';
      chip.addEventListener('click', function () {
        activeTagId = activeTagId === tagId ? null : tagId;
        exitSelectMode();
        renderDocuments();
      });
      tagFilter.appendChild(chip);
    }

    addChip(null, t('allTags'));
    usedTags.forEach(function (tag) { addChip(tag.id, tag.name); });
  }

  function visibleDocuments() {
    if (!activeTagId) return documents;
    return documents.filter(function (doc) { return doc.tags.indexOf(activeTagId) !== -1; });
  }

  function renderDocuments() {
    renderTagFilter();
    documentList.innerHTML = '';
    var docs = visibleDocuments();
    emptyList.hidden = !activeSectionId || docs.length > 0;
    emptyList.textContent = activeTagId ? t('emptyTag') : t('emptySection');

    docs.forEach(function (doc) {
      var card = el('div', 'document-card');
      var thumb = el('div', 'thumb');
      var first = doc.pages[0];
      if (first && first.editable) {
        var img = el('img');
        img.src = thumbnailUrl(doc, first);
        img.loading = 'lazy';
        img.alt = '';
        thumb.appendChild(img);
      } else {
        thumb.innerHTML = icon('file-text');
        // A scanned file can have an empty ext (see CLAUDE.md, Scan): icon only then.
        if (first && first.ext) thumb.appendChild(el('span', 'thumb-ext', extLabel(first)));
      }
      if (doc.pages.length > 1) thumb.appendChild(el('span', 'page-badge', doc.pages.length));
      if (selectMode) {
        var checkbox = el('input', 'select-checkbox');
        checkbox.type = 'checkbox';
        checkbox.tabIndex = -1;
        checkbox.checked = selectedIds.indexOf(doc.id) !== -1;
        thumb.appendChild(checkbox);
        card.classList.toggle('selected', checkbox.checked);
      }
      card.appendChild(thumb);
      card.appendChild(el('div', 'doc-title', doc.title));
      card.appendChild(el('div', 'doc-meta', formatDate(doc.date)));
      card.addEventListener('click', function () {
        if (selectMode) toggleSelected(doc.id, card); else openView(doc);
      });
      documentList.appendChild(card);
    });
  }

  // --- selection + zip download ---------------------------------------------------

  function exitSelectMode() {
    selectMode = false;
    selectedIds = [];
    selectModeBtn.querySelector('.btn-label').textContent = t('select');
    selectModeBtn.title = t('select');
    selectionBar.hidden = true;
    documentList.classList.remove('with-selection-bar');
  }

  function updateSelectionBar() {
    selectionCount.textContent = t('selectedCount', { n: selectedIds.length });
  }

  function toggleSelected(docId, card) {
    var idx = selectedIds.indexOf(docId);
    if (idx === -1) selectedIds.push(docId); else selectedIds.splice(idx, 1);
    card.classList.toggle('selected', idx === -1);
    card.querySelector('.select-checkbox').checked = idx === -1;
    updateSelectionBar();
  }

  selectModeBtn.addEventListener('click', function () {
    if (selectMode) {
      exitSelectMode();
    } else {
      selectMode = true;
      selectedIds = [];
      selectModeBtn.querySelector('.btn-label').textContent = t('cancel');
      selectModeBtn.title = t('cancel');
      selectionBar.hidden = false;
      documentList.classList.add('with-selection-bar');
      updateSelectionBar();
    }
    renderDocuments();
  });

  $('cancelSelection').addEventListener('click', function () {
    exitSelectMode();
    renderDocuments();
  });

  // A GET download keeps the name the server gives it (Content-Disposition).
  function saveUrl(url, name) {
    var a = el('a');
    a.href = url;
    a.download = name || '';
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  function downloadZip(ids) {
    return fetch('api/documents/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: ids })
    }).then(function (res) {
      if (!res.ok) throw new Error('download failed');
      return res.blob();
    }).then(function (blob) {
      var url = URL.createObjectURL(blob);
      saveUrl(url, 'papelada.zip');
      URL.revokeObjectURL(url);
    });
  }

  $('downloadSelected').addEventListener('click', function () {
    if (!selectedIds.length) return;
    downloadZip(selectedIds).then(function () {
      exitSelectMode();
      renderDocuments();
    });
  });

  // --- view dialog -------------------------------------------------------------------

  function renderTagChips(container, tagIds) {
    container.innerHTML = '';
    tags.forEach(function (tag) {
      if (tagIds.indexOf(tag.id) !== -1) container.appendChild(el('span', 'chip', tag.name));
    });
    container.hidden = !container.children.length;
  }

  function openView(doc) {
    viewingDoc = doc;
    var section = findById(sections, doc.section);
    $('viewTitle').textContent = doc.title;
    $('viewMeta').textContent = formatDate(doc.date) + (section ? ' · ' + section.name : '');
    renderTagChips($('viewTags'), doc.tags);

    renderViewPages();
    setDownloadMenu(false);
    viewDialog.showModal();
  }

  function renderViewPages() {
    var doc = viewingDoc;
    viewPages.innerHTML = '';
    doc.pages.forEach(function (page) {
      var url = contentUrl(doc, page);
      var figure = el('figure', 'view-page');
      if (isPreviewable(page) && isImage(page)) {
        var img = el('img');
        img.src = url;
        img.alt = '';
        figure.appendChild(img);
      } else if (page.mime === 'application/pdf') {
        var frame = el('iframe');
        frame.src = url;
        figure.appendChild(frame);
      } else if (page.editable) {
        // An image the browser can't show (TIFF, BMP): the thumbnail stands in.
        var thumb = el('img');
        thumb.src = thumbnailUrl(doc, page);
        thumb.alt = '';
        figure.appendChild(thumb);
      } else {
        var none = el('div', 'no-preview');
        none.innerHTML = icon('file');
        none.appendChild(el('span', null, t('noPreview')));
        figure.appendChild(none);
      }

      // In plain mode this is where the file actually is in the volume;
      // encrypted, it's just the name it downloads with.
      var caption = el('figcaption');
      var name = el('span', 'file-path', encrypted ? page.path.split('/').pop() : page.path);
      caption.appendChild(name);
      if (page.editable) {
        var edit = iconButton('sliders-horizontal', t('editPage'), function () {
          openPageEditor(doc, page, function () {
            renderViewPages();
            refresh();
          });
        });
        edit.className = 'caption-button';
        caption.appendChild(edit);
      }
      if (isPreviewable(page)) {
        var open = el('a', null, t('openFile'));
        open.href = url;
        open.target = '_blank';
        open.rel = 'noopener';
        caption.appendChild(open);
      }
      var download = el('a');
      download.href = url + '&download=1';
      download.title = t('download');
      download.setAttribute('aria-label', t('download'));
      download.innerHTML = icon('download');
      caption.appendChild(download);
      figure.appendChild(caption);
      viewPages.appendChild(figure);
    });
  }

  closeOnBackdropClick(viewDialog);

  $('closeViewBtn').addEventListener('click', function () { viewDialog.close(); });

  // --- document download: its files, or one PDF ------------------------------------------

  // A single PDF needs every page to be an image or a PDF; for a document that
  // already is one PDF file, it would just be that file again.
  function canDownloadPdf(doc) {
    var convertible = doc.pages.every(function (page) { return page.editable || page.mime === 'application/pdf'; });
    return convertible && !(doc.pages.length === 1 && doc.pages[0].mime === 'application/pdf');
  }

  function downloadFiles(doc) {
    if (doc.pages.length === 1) saveUrl(contentUrl(doc, doc.pages[0]) + '&download=1');
    else downloadZip([doc.id]);
  }

  function setDownloadMenu(open) {
    downloadMenu.hidden = !open;
    $('downloadDocumentBtn').setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  $('downloadDocumentBtn').addEventListener('click', function (ev) {
    ev.stopPropagation();
    var doc = viewingDoc;
    if (!canDownloadPdf(doc)) {
      downloadFiles(doc);
      return;
    }
    $('downloadFilesLabel').textContent = t(doc.pages.length === 1 ? 'downloadFile' : 'downloadZip');
    setDownloadMenu(downloadMenu.hidden);
  });

  $('downloadFilesBtn').addEventListener('click', function () {
    setDownloadMenu(false);
    downloadFiles(viewingDoc);
  });

  $('downloadPdfBtn').addEventListener('click', function () {
    setDownloadMenu(false);
    saveUrl('api/documents/' + viewingDoc.id + '/pdf');
  });

  viewDialog.addEventListener('click', function (ev) {
    if (!downloadMenu.hidden && !downloadMenu.contains(ev.target)) setDownloadMenu(false);
  });

  $('editDocumentBtn').addEventListener('click', function () {
    if (!viewingDoc) return;
    viewDialog.close();
    openDocumentDialog(viewingDoc);
  });

  $('deleteDocumentBtn').addEventListener('click', function () {
    if (!viewingDoc) return;
    var doc = viewingDoc;
    confirmAction(t('confirmDeleteDocument')).then(function (ok) {
      if (!ok) return;
      api('DELETE', 'api/documents/' + doc.id).then(function () {
        viewDialog.close();
        refresh();
      });
    });
  });

  // --- new/edit document dialog -----------------------------------------------------

  function renderSectionSelect(selectedId) {
    sectionSelect.innerHTML = '';
    sections.forEach(function (section) {
      var option = el('option', null, section.name);
      option.value = section.id;
      option.selected = section.id === selectedId;
      sectionSelect.appendChild(option);
    });
  }

  function renderFormTags() {
    formTags.innerHTML = '';
    tags.forEach(function (tag) {
      var chip = el('button', formTagIds.indexOf(tag.id) !== -1 ? 'active' : '', tag.name);
      chip.type = 'button';
      chip.addEventListener('click', function () {
        var idx = formTagIds.indexOf(tag.id);
        if (idx === -1) formTagIds.push(tag.id); else formTagIds.splice(idx, 1);
        renderFormTags();
      });
      formTags.appendChild(chip);
    });
  }

  function addTagFromForm() {
    var name = newTagInput.value.trim();
    if (!name) return;
    var existing = tags.filter(function (tag) { return tag.name.toLowerCase() === name.toLowerCase(); })[0];
    if (existing) {
      if (formTagIds.indexOf(existing.id) === -1) formTagIds.push(existing.id);
      newTagInput.value = '';
      renderFormTags();
      return;
    }
    api('POST', 'api/tags', { name: name }).then(function (tag) {
      tags.push(tag);
      tags.sort(function (a, b) { return a.name.localeCompare(b.name); });
      formTagIds.push(tag.id);
      newTagInput.value = '';
      documentStatus.textContent = '';
      renderFormTags();
    }).catch(function (err) {
      documentStatus.textContent = errorMessage(err);
    });
  }

  $('addTagBtn').addEventListener('click', addTagFromForm);
  newTagInput.addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter') {
      ev.preventDefault();
      addTagFromForm();
    }
  });

  function previewTile(content, onRemove) {
    var item = el('div', 'page-preview-item');
    item.appendChild(content);
    if (onRemove) {
      var remove = iconButton('x', t('removePage'), onRemove);
      remove.className = 'remove-page';
      item.appendChild(remove);
    }
    return item;
  }

  function fileIconTile(label) {
    var box = el('div', 'page-preview-icon');
    box.innerHTML = icon('file-text');
    if (label) box.appendChild(el('span', 'page-preview-name', label));
    return box;
  }

  function renderPendingPages() {
    pendingPagesEl.innerHTML = '';
    pendingFiles.forEach(function (file, index) {
      var content;
      if (file.type.indexOf('image/') === 0) {
        content = el('img');
        content.src = URL.createObjectURL(file);
        content.alt = '';
      } else {
        content = fileIconTile(file.name);
      }
      pendingPagesEl.appendChild(previewTile(content, function () {
        pendingFiles.splice(index, 1);
        renderPendingPages();
      }));
    });
  }

  // Image pages open the page editor; anything else just shows its type.
  function renderEditPages() {
    editPagesEl.innerHTML = '';
    editingDoc.pages.forEach(function (page) {
      if (!page.editable) {
        editPagesEl.appendChild(previewTile(fileIconTile(extLabel(page))));
        return;
      }
      var tile = el('button', 'page-preview-item editable');
      tile.type = 'button';
      tile.title = t('editPage');
      tile.setAttribute('aria-label', t('editPage'));
      var img = el('img');
      img.src = thumbnailUrl(editingDoc, page);
      img.alt = '';
      tile.appendChild(img);
      var badge = el('span', 'page-edit-badge');
      badge.innerHTML = icon('sliders-horizontal');
      tile.appendChild(badge);
      tile.addEventListener('click', function () {
        openPageEditor(editingDoc, page, function () {
          pagesChangedDuringEdit = true;
          renderEditPages();
        });
      });
      editPagesEl.appendChild(tile);
    });
  }

  function openDocumentDialog(doc) {
    editingDoc = doc || null;
    pagesChangedDuringEdit = false;
    $('documentDialogTitle').textContent = t(doc ? 'editDocument' : 'newDocument');
    $('submitDocument').textContent = t(doc ? 'save' : 'upload');
    titleInput.value = doc ? doc.title : '';
    dateInput.value = doc ? doc.date : todayIso();
    renderSectionSelect(doc ? doc.section : activeSectionId);
    formTagIds = doc ? doc.tags.slice() : (activeTagId ? [activeTagId] : []);
    newTagInput.value = '';
    pendingFiles = [];
    documentStatus.textContent = '';
    newPagesField.hidden = !!doc;
    editPagesField.hidden = !doc;
    renderFormTags();
    if (doc) renderEditPages(); else renderPendingPages();
    documentDialog.showModal();
  }

  $('takePhotoBtn').addEventListener('click', function () {
    cameraInput.value = '';
    cameraInput.click();
  });

  $('addFilesBtn').addEventListener('click', function () {
    filesInput.value = '';
    filesInput.click();
  });

  // Photos are taken one at a time (multiple + capture is unreliable on phones),
  // so a document with several pages is built up by tapping "Take photo" again.
  function addPendingFiles(fileList) {
    for (var i = 0; i < fileList.length; i++) pendingFiles.push(fileList[i]);
    renderPendingPages();
  }

  cameraInput.addEventListener('change', function () { addPendingFiles(cameraInput.files); });
  filesInput.addEventListener('change', function () { addPendingFiles(filesInput.files); });

  $('cancelDocument').addEventListener('click', function () {
    documentDialog.close();
    if (pagesChangedDuringEdit) refresh();
  });

  $('documentForm').addEventListener('submit', function (ev) {
    ev.preventDefault();
    var title = titleInput.value.trim();
    if (!title) {
      documentStatus.textContent = t('errors.title_required');
      return;
    }
    if (!dateInput.value) {
      documentStatus.textContent = t('errors.invalid_date');
      return;
    }
    var sectionId = sectionSelect.value;
    var request;

    if (editingDoc) {
      documentStatus.textContent = t('saving');
      request = api('PUT', 'api/documents/' + editingDoc.id, {
        title: title, date: dateInput.value, section: sectionId, tags: formTagIds
      });
    } else {
      if (!pendingFiles.length) {
        documentStatus.textContent = t('needPages');
        return;
      }
      var form = new FormData();
      form.append('section', sectionId);
      form.append('title', title);
      form.append('date', dateInput.value);
      formTagIds.forEach(function (tagId) { form.append('tags', tagId); });
      pendingFiles.forEach(function (file) { form.append('files', file); });
      documentStatus.textContent = t('uploading');
      request = api('POST', 'api/documents', form);
    }

    request.then(function () {
      documentDialog.close();
      if (sectionId !== activeSectionId && !editingDoc) setActiveSection(sectionId);
      refresh();
    }).catch(function (err) {
      documentStatus.textContent = errorMessage(err);
    });
  });

  // --- page editor ------------------------------------------------------------------------
  //
  // Edits are a recipe the server applies to the page as uploaded (see
  // app/images.py): rotation, a crop box, a filter, a size and a format. The
  // editor draws on a scaled-down preview of that upload: rotation is done here
  // on a canvas, Cropper.js only draws the box, and the box is sent as fractions
  // of the rotated image, so the preview's size doesn't matter.

  function openPageEditor(doc, page, onChange) {
    editor = {
      doc: doc,
      pages: doc.pages.filter(function (p) { return p.editable; }),
      onChange: onChange,
      changed: false
    };
    editorDialog.showModal();
    loadEditorPage(indexOfPage(page.id));
  }

  function indexOfPage(pageId) {
    for (var i = 0; i < editor.pages.length; i++) {
      if (editor.pages[i].id === pageId) return i;
    }
    return 0;
  }

  function loadEditorPage(index) {
    var page = editor.pages[index];
    var edits = page.edits || {};
    editor.index = index;
    editor.page = page;
    editor.rotate = edits.rotate || 0;
    editor.crop = edits.crop || null;
    editor.filter = edits.filter || null;
    editor.reduce = !!edits.reduce;
    editor.format = edits.format || '';
    editor.saved = editorStateKey(editor.crop);
    editor.preview = null;

    $('editorTitle').textContent = editor.doc.title;
    $('editorNav').hidden = editor.pages.length < 2;
    $('editorPosition').textContent = t('pageOf', { n: index + 1, total: editor.pages.length });
    $('editorPrev').disabled = index === 0;
    $('editorNext').disabled = index === editor.pages.length - 1;
    $('restorePageBtn').hidden = !page.edited;
    editorStatus.textContent = '';
    setEditorBusy(false);
    renderFormatOptions(page);
    renderEditorToggles();

    destroyCropper();
    var preview = new Image();
    preview.onload = function () {
      if (editor && editor.page === page) {
        editor.preview = preview;
        drawEditorImage();
      }
    };
    preview.onerror = function () { editorStatus.textContent = t('errors.unreadable_image'); };
    preview.src = pageUrl(editor.doc, page, 'preview');
  }

  function renderFormatOptions(page) {
    var sourceExt = (page.original_ext || page.ext || '').slice(1).toUpperCase();
    formatSelect.innerHTML = '';
    [['', t('formatKeep', { ext: sourceExt || '?' })], ['png', 'PNG'], ['pdf', 'PDF']].forEach(function (option) {
      if (option[0] === 'png' && sourceExt === 'PNG') return;  // keeping it already is PNG
      var node = el('option', null, option[1]);
      node.value = option[0];
      formatSelect.appendChild(node);
    });
    formatSelect.value = editor.format;
  }

  function renderEditorToggles() {
    $('scanFilterBtn').setAttribute('aria-pressed', editor.filter === 'scan' ? 'true' : 'false');
    $('reduceBtn').setAttribute('aria-pressed', editor.reduce ? 'true' : 'false');
    editorStage.classList.toggle('filter-scan', editor.filter === 'scan');
  }

  function destroyCropper() {
    if (cropper) {
      cropper.destroy();
      cropper = null;
    }
    if (editor) editor.ready = false;
    editorImage.onload = null;
    if (editorImage.src.indexOf('blob:') === 0) URL.revokeObjectURL(editorImage.src);
    editorImage.removeAttribute('src');
  }

  // Draws the preview turned by editor.rotate and puts the crop box on it.
  function drawEditorImage() {
    var source = editor.preview;
    var quarter = editor.rotate % 180 !== 0;
    var canvas = el('canvas');
    canvas.width = quarter ? source.naturalHeight : source.naturalWidth;
    canvas.height = quarter ? source.naturalWidth : source.naturalHeight;
    var ctx = canvas.getContext('2d');
    ctx.translate(canvas.width / 2, canvas.height / 2);
    ctx.rotate(editor.rotate * Math.PI / 180);
    ctx.drawImage(source, -source.naturalWidth / 2, -source.naturalHeight / 2);
    var page = editor.page;
    canvas.toBlob(function (blob) {
      if (!editor || editor.page !== page) return;
      destroyCropper();
      editorImage.onload = function () {
        cropper = new Cropper(editorImage, {
          viewMode: 1, autoCropArea: 1, background: false, movable: false, zoomable: false,
          rotatable: false, scalable: false, checkOrientation: false,
          ready: function () {
            if (editor.crop) cropper.setData(cropToData(editor.crop));
            editor.ready = true;
          }
        });
      };
      editorImage.src = URL.createObjectURL(blob);
    }, 'image/jpeg', 0.9);
  }

  function cropToData(crop) {
    var image = cropper.getImageData();
    return {
      x: crop.x * image.naturalWidth, y: crop.y * image.naturalHeight,
      width: crop.w * image.naturalWidth, height: crop.h * image.naturalHeight
    };
  }

  // The crop box as fractions of the (rotated) image, or null for the whole image.
  function currentCrop() {
    if (!cropper || !editor.ready) return editor.crop;
    var data = cropper.getData();
    var image = cropper.getImageData();
    var crop = {
      x: Math.max(0, data.x / image.naturalWidth), y: Math.max(0, data.y / image.naturalHeight),
      w: Math.min(1, data.width / image.naturalWidth), h: Math.min(1, data.height / image.naturalHeight)
    };
    var whole = crop.x < 0.001 && crop.y < 0.001 && crop.w > 0.999 && crop.h > 0.999;
    return whole ? null : crop;
  }

  // Rounded so that redrawing the same box doesn't count as a change.
  function editorStateKey(crop) {
    return JSON.stringify([
      editor.rotate, editor.filter, editor.reduce, editor.format,
      crop && [crop.x, crop.y, crop.w, crop.h].map(function (v) { return Math.round(v * 500); })
    ]);
  }

  function editorDirty() {
    return editorStateKey(currentCrop()) !== editor.saved;
  }

  // The box turns with the image, so a crop survives a rotation.
  function rotateEditor(clockwise) {
    var crop = currentCrop();
    if (crop) {
      crop = clockwise
        ? { x: 1 - crop.y - crop.h, y: crop.x, w: crop.h, h: crop.w }
        : { x: crop.y, y: 1 - crop.x - crop.w, w: crop.h, h: crop.w };
    }
    editor.crop = crop;
    editor.rotate = (editor.rotate + (clockwise ? 90 : 270)) % 360;
    if (editor.preview) drawEditorImage();
  }

  function setEditorBusy(busy) {
    ['saveEditor', 'restorePageBtn', 'editorPrev', 'editorNext'].forEach(function (id) { $(id).disabled = busy; });
    if (!busy && editor) {
      $('editorPrev').disabled = editor.index === 0;
      $('editorNext').disabled = editor.index === editor.pages.length - 1;
    }
  }

  // Puts the page the server sent back into the document (and so the dialog below).
  function editorPageUpdated(updated) {
    editor.doc.pages = editor.doc.pages.map(function (p) { return p.id === updated.id ? updated : p; });
    editor.pages[editor.index] = updated;
    editor.changed = true;
  }

  function closePageEditor() {
    var done = editor;
    destroyCropper();
    editorDialog.close();
    editor = null;
    if (done && done.changed && done.onChange) done.onChange();
  }

  function leaveEditorPage(then) {
    if (!editorDirty()) {
      then();
      return;
    }
    confirmAction(t('discardChanges'), t('discard')).then(function (ok) {
      if (ok) then();
    });
  }

  $('rotateLeftBtn').addEventListener('click', function () { rotateEditor(false); });
  $('rotateRightBtn').addEventListener('click', function () { rotateEditor(true); });

  $('scanFilterBtn').addEventListener('click', function () {
    editor.filter = editor.filter === 'scan' ? null : 'scan';
    renderEditorToggles();
  });

  $('reduceBtn').addEventListener('click', function () {
    editor.reduce = !editor.reduce;
    renderEditorToggles();
  });

  formatSelect.addEventListener('change', function () { editor.format = formatSelect.value; });

  $('editorPrev').addEventListener('click', function () {
    leaveEditorPage(function () { loadEditorPage(editor.index - 1); });
  });

  $('editorNext').addEventListener('click', function () {
    leaveEditorPage(function () { loadEditorPage(editor.index + 1); });
  });

  $('cancelEditor').addEventListener('click', closePageEditor);

  // Esc closes the dialog without going through Cancel.
  editorDialog.addEventListener('cancel', function (ev) {
    ev.preventDefault();
    closePageEditor();
  });

  $('saveEditor').addEventListener('click', function () {
    var edits = {
      rotate: editor.rotate,
      crop: currentCrop(),
      filter: editor.filter,
      reduce: editor.reduce,
      format: editor.format || null
    };
    setEditorBusy(true);
    editorStatus.textContent = t('saving');
    api('PUT', 'api/documents/' + editor.doc.id + '/pages/' + editor.page.id + '/edits', edits).then(function (page) {
      editorPageUpdated(page);
      closePageEditor();
    }).catch(function (err) {
      editorStatus.textContent = errorMessage(err);
      setEditorBusy(false);
    });
  });

  $('restorePageBtn').addEventListener('click', function () {
    setEditorBusy(true);
    api('POST', 'api/documents/' + editor.doc.id + '/pages/' + editor.page.id + '/restore').then(function (page) {
      editorPageUpdated(page);
      loadEditorPage(editor.index);
    }).catch(function (err) {
      editorStatus.textContent = errorMessage(err);
      setEditorBusy(false);
    });
  });

  // --- sections ------------------------------------------------------------------------

  function renderIconGrid() {
    iconGrid.innerHTML = '';
    SECTION_ICONS.forEach(function (name) {
      var btn = iconButton(name, name, function () {
        chosenIcon = name;
        renderIconGrid();
      });
      if (name === chosenIcon) btn.className = 'active';
      iconGrid.appendChild(btn);
    });
  }

  function openSectionDialog(section) {
    editingSection = section;
    chosenIcon = section ? section.icon : 'folder';
    $('sectionDialogTitle').textContent = t(section ? 'editSection' : 'newSection');
    sectionNameInput.value = section ? section.name : '';
    $('sectionFolderHint').textContent = section && !encrypted ? t('folderHint', { folder: section.folder }) : '';
    $('deleteSectionBtn').hidden = !section;
    sectionStatus.textContent = '';
    renderIconGrid();
    sectionDialog.showModal();
    var active = iconGrid.querySelector('.active');
    if (active) active.scrollIntoView({ block: 'nearest' });
  }

  $('cancelSection').addEventListener('click', function () { sectionDialog.close(); });

  $('sectionForm').addEventListener('submit', function (ev) {
    ev.preventDefault();
    var body = { name: sectionNameInput.value.trim(), icon: chosenIcon };
    if (!body.name) {
      sectionStatus.textContent = t('errors.name_required');
      return;
    }
    var request = editingSection
      ? api('PUT', 'api/sections/' + editingSection.id, body)
      : api('POST', 'api/sections', body);
    request.then(function (section) {
      sectionDialog.close();
      if (!editingSection) setActiveSection(section.id);
      refresh();
    }).catch(function (err) {
      sectionStatus.textContent = errorMessage(err);
    });
  });

  $('deleteSectionBtn').addEventListener('click', function () {
    var section = editingSection;
    if (section.documents > 0) {
      sectionStatus.textContent = t('errors.section_not_empty');
      return;
    }
    confirmAction(t('confirmDeleteSection', { name: section.name })).then(function (ok) {
      if (!ok) return;
      api('DELETE', 'api/sections/' + section.id).then(function () {
        sectionDialog.close();
        refresh();
      }).catch(function (err) {
        sectionStatus.textContent = errorMessage(err);
      });
    });
  });

  $('welcomeNewSection').addEventListener('click', function () { openSectionDialog(null); });

  // --- sections and tags manager ----------------------------------------------------------

  function moveSection(index, delta) {
    var ids = sections.map(function (s) { return s.id; });
    var target = index + delta;
    if (target < 0 || target >= ids.length) return;
    ids.splice(target, 0, ids.splice(index, 1)[0]);
    api('POST', 'api/sections/reorder', { ids: ids }).then(function (list) {
      sections = list;
      renderSections();
      renderManage();
    });
  }

  function manageRow(iconName, name, count, buttons) {
    var row = el('li');
    if (iconName) {
      var glyph = el('span', 'row-icon');
      glyph.innerHTML = icon(iconName);
      row.appendChild(glyph);
    }
    var label = el('span', 'row-label');
    label.appendChild(el('span', 'row-name', name));
    label.appendChild(el('span', 'row-count', t('docCount', { n: count })));
    row.appendChild(label);
    var actions = el('span', 'row-actions');
    buttons.forEach(function (btn) { actions.appendChild(btn); });
    row.appendChild(actions);
    return row;
  }

  function renderThemes() {
    var grid = $('themeGrid');
    grid.innerHTML = '';
    var active = THEME.current().id;
    THEMES.forEach(function (theme) {
      var btn = el('button', theme.id === active ? 'active' : '');
      btn.type = 'button';
      var swatch = el('span', 'theme-swatch');
      swatch.style.background = theme.bg;
      var bar = el('i');
      bar.style.background = theme.accent;
      swatch.appendChild(bar);
      btn.appendChild(swatch);
      btn.appendChild(el('span', null, t('theme.' + theme.id)));
      btn.addEventListener('click', function () {
        THEME.set(theme.id);
        renderThemes();
      });
      grid.appendChild(btn);
    });
  }

  function renderManage() {
    renderThemes();
    $('stripMetadataInput').checked = uploadSettings.strip_metadata;
    $('reduceUploadsInput').checked = uploadSettings.reduce_uploads;
    $('scanField').hidden = encrypted;
    var sectionList = $('manageSections');
    sectionList.innerHTML = '';
    sections.forEach(function (section, index) {
      var up = iconButton('chevron-up', t('moveUp'), function () { moveSection(index, -1); });
      var down = iconButton('chevron-down', t('moveDown'), function () { moveSection(index, 1); });
      up.disabled = index === 0;
      down.disabled = index === sections.length - 1;
      var edit = iconButton('pencil', t('edit'), function () { openSectionDialog(section); });
      sectionList.appendChild(manageRow(section.icon, section.name, section.documents, [up, down, edit]));
    });

    var tagList = $('manageTags');
    tagList.innerHTML = '';
    if (!tags.length) tagList.appendChild(el('li', 'empty-row', t('noTags')));
    tags.forEach(function (tag) {
      var rename = iconButton('pencil', t('renameTag'), function () {
        openNameDialog(t('renameTag'), tag.name, function (name) {
          return api('PUT', 'api/tags/' + tag.id, { name: name });
        });
      });
      var remove = iconButton('trash', t('delete'), function () {
        confirmAction(t('confirmDeleteTag', { name: tag.name })).then(function (ok) {
          if (ok) api('DELETE', 'api/tags/' + tag.id).then(refresh);
        });
      });
      tagList.appendChild(manageRow(null, tag.name, tag.documents, [rename, remove]));
    });
  }

  [['stripMetadataInput', 'strip_metadata'], ['reduceUploadsInput', 'reduce_uploads']].forEach(function (pair) {
    var input = $(pair[0]);
    input.addEventListener('change', function () {
      var body = {};
      body[pair[1]] = input.checked;
      $('uploadSettingsStatus').textContent = '';
      api('PUT', 'api/settings', body).then(function (settings) {
        uploadSettings = { strip_metadata: settings.strip_metadata, reduce_uploads: settings.reduce_uploads };
      }).catch(function (err) {
        input.checked = !input.checked;
        $('uploadSettingsStatus').textContent = errorMessage(err);
      });
    });
  });

  $('manageBtn').addEventListener('click', function () {
    $('scanStatus').textContent = '';
    $('uploadSettingsStatus').textContent = '';
    renderManage();
    manageDialog.showModal();
  });

  closeOnBackdropClick(manageDialog);
  $('closeManage').addEventListener('click', function () { manageDialog.close(); });
  $('manageNewSection').addEventListener('click', function () { openSectionDialog(null); });
  $('scanBtn').addEventListener('click', function () {
    $('scanBtn').disabled = true;
    $('scanStatus').textContent = t('scanning');
    api('POST', 'api/scan').then(function (result) {
      $('scanStatus').textContent = t('scanResult', result);
      return refresh();
    }).catch(function (err) {
      $('scanStatus').textContent = errorMessage(err);
    }).then(function () {
      $('scanBtn').disabled = false;
    });
  });

  $('manageNewTag').addEventListener('click', function () {
    openNameDialog(t('newTag'), '', function (name) {
      return api('POST', 'api/tags', { name: name });
    });
  });

  function openNameDialog(title, value, save) {
    $('nameDialogTitle').textContent = title;
    nameInput.value = value;
    nameStatus.textContent = '';
    nameDialogSave = save;
    nameDialog.showModal();
  }

  $('cancelName').addEventListener('click', function () { nameDialog.close(); });

  $('nameForm').addEventListener('submit', function (ev) {
    ev.preventDefault();
    var name = nameInput.value.trim();
    if (!name) {
      nameStatus.textContent = t('errors.name_required');
      return;
    }
    nameDialogSave(name).then(function () {
      nameDialog.close();
      refresh();
    }).catch(function (err) {
      nameStatus.textContent = errorMessage(err);
    });
  });

  // --- encryption ------------------------------------------------------------------------

  function renderSecurity() {
    document.querySelector('#securityBtn .btn-icon').innerHTML = icon(encrypted ? 'lock' : 'lock-open');
    $('securityState').textContent = t(encrypted ? 'encryptionOn' : 'encryptionOff');
    $('securityHelp').textContent = t(!encryptionAvailable && !encrypted ? 'encryptionUnavailableHelp'
      : encrypted ? 'encryptionOnHelp' : 'encryptionOffHelp');
    toggleEncryptionBtn.textContent = t(encrypted ? 'decryptAll' : 'encryptAll');
    toggleEncryptionBtn.hidden = !encryptionAvailable;
  }

  function setSecurityBusy(busy) {
    toggleEncryptionBtn.disabled = busy;
    $('closeSecurity').disabled = busy;
  }

  $('securityBtn').addEventListener('click', function () {
    securityStatus.textContent = '';
    renderSecurity();
    securityDialog.showModal();
  });

  // Not while converting: Close is disabled then too.
  closeOnBackdropClick(securityDialog, function () { return !$('closeSecurity').disabled; });
  $('closeSecurity').addEventListener('click', function () { securityDialog.close(); });

  toggleEncryptionBtn.addEventListener('click', function () {
    setSecurityBusy(true);
    securityStatus.textContent = t('converting');
    api('PUT', 'api/settings', { encrypted: !encrypted }).then(function (result) {
      encrypted = result.encrypted;
      renderSecurity();
      securityStatus.textContent = t('convertedCount', { n: result.converted });
      refresh();
    }).catch(function (err) {
      securityStatus.textContent = errorMessage(err);
      return loadSettings().catch(function () {});
    }).then(function () {
      setSecurityBusy(false);
    });
  });

  // --- login ------------------------------------------------------------------------------

  // Not dismissable: there's nothing to show until the session is valid.
  loginDialog.addEventListener('cancel', function (ev) { ev.preventDefault(); });

  function showLogin() {
    if (loginDialog.open) return;
    $('logoutBtn').hidden = true;
    passwordInput.value = '';
    loginStatus.textContent = '';
    loginDialog.showModal();
    (usernameInput.value ? passwordInput : usernameInput).focus();
  }

  $('loginForm').addEventListener('submit', function (ev) {
    ev.preventDefault();
    $('loginSubmit').disabled = true;
    loginStatus.textContent = t('signingIn');
    api('POST', 'api/login', { username: usernameInput.value, password: passwordInput.value }).then(function () {
      passwordInput.value = '';
      loginDialog.close();
      start(true);
    }).catch(function (err) {
      loginStatus.textContent = errorMessage(err);
      passwordInput.select();
    }).then(function () {
      $('loginSubmit').disabled = false;
    });
  });

  $('logoutBtn').addEventListener('click', function () {
    api('POST', 'api/logout').catch(function () {}).then(function () {
      // Reload rather than clear every bit of state by hand: nothing of the library stays on screen.
      location.reload();
    });
  });

  // --- start ------------------------------------------------------------------------------

  $('uploadBtn').addEventListener('click', function () {
    if (sections.length) openDocumentDialog(null); else openSectionDialog(null);
  });

  function start(loginRequired) {
    $('logoutBtn').hidden = !loginRequired;
    loadSettings().catch(function () {});
    refresh();
  }

  api('GET', 'api/session').then(function (session) {
    if (session.authenticated) start(session.login_required); else showLogin();
  }).catch(function () {
    start(false);
  });
})();
