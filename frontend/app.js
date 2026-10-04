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

  var cropDialog = $('cropDialog');
  var cropImage = $('cropImage');
  var cropStatus = $('cropStatus');

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

  I18N.apply(document);
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
  $('addTagBtn').innerHTML = icon('plus');
  $('editDocumentBtn').innerHTML = icon('pencil');
  $('deleteDocumentBtn').innerHTML = icon('trash');
  $('closeViewBtn').innerHTML = icon('x');

  // --- state ------------------------------------------------------------------

  var sections = [];
  var tags = [];
  var documents = [];  // every document of the active section; the tag filter is applied when rendering
  var activeSectionId = null;
  var activeTagId = null;
  var encrypted = false;
  var encryptionAvailable = false;

  var viewingDoc = null;
  var editingDoc = null;
  var formTagIds = [];
  var pendingFiles = [];
  var pagesChangedDuringEdit = false;
  var selectMode = false;
  var selectedIds = [];
  var cropper = null;
  var croppingPage = null;
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

  function contentUrl(doc, page) {
    return 'api/documents/' + doc.id + '/pages/' + page.id + '/content?v=' + page.rev;
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
      if (first && isImage(first) && isPreviewable(first)) {
        var img = el('img');
        img.src = contentUrl(doc, first);
        img.loading = 'lazy';
        img.alt = '';
        thumb.appendChild(img);
      } else {
        thumb.innerHTML = icon('file-text');
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

  $('downloadSelected').addEventListener('click', function () {
    if (!selectedIds.length) return;
    fetch('api/documents/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: selectedIds })
    }).then(function (res) {
      if (!res.ok) throw new Error('download failed');
      return res.blob();
    }).then(function (blob) {
      var url = URL.createObjectURL(blob);
      var a = el('a');
      a.href = url;
      a.download = 'papelada.zip';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
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
    viewDialog.showModal();
  }

  // Backdrop clicks are dispatched to the dialog element itself, so check the
  // position too; a drag that merely ends outside the box doesn't count.
  function closeOnBackdropClick(dialog) {
    var pressedOutside = false;
    function isOutside(ev) {
      var box = dialog.getBoundingClientRect();
      return ev.target === dialog &&
        (ev.clientX < box.left || ev.clientX > box.right || ev.clientY < box.top || ev.clientY > box.bottom);
    }
    dialog.addEventListener('pointerdown', function (ev) { pressedOutside = isOutside(ev); });
    dialog.addEventListener('click', function (ev) {
      if (pressedOutside && isOutside(ev)) dialog.close();
    });
  }

  closeOnBackdropClick(viewDialog);

  $('closeViewBtn').addEventListener('click', function () { viewDialog.close(); });

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

  function fileIconTile() {
    var box = el('div', 'page-preview-icon');
    box.innerHTML = icon('file-text');
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
        content = fileIconTile();
        content.appendChild(el('span', 'page-preview-name', file.name));
      }
      pendingPagesEl.appendChild(previewTile(content, function () {
        pendingFiles.splice(index, 1);
        renderPendingPages();
      }));
    });
  }

  function renderEditPages() {
    editPagesEl.innerHTML = '';
    editingDoc.pages.forEach(function (page) {
      if (!(isImage(page) && isPreviewable(page))) {
        editPagesEl.appendChild(previewTile(fileIconTile()));
        return;
      }
      var img = el('img');
      img.src = contentUrl(editingDoc, page);
      img.alt = '';
      var item = previewTile(img);
      var tools = el('div', 'page-tools');
      tools.appendChild(iconButton('scissors', t('crop'), function () { openCropDialog(page); }));
      if (page.cropped) {
        tools.appendChild(iconButton('rotate-ccw', t('restoreOriginal'), function () { restorePage(page); }));
      }
      item.appendChild(tools);
      editPagesEl.appendChild(item);
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

  // --- crop ---------------------------------------------------------------------------

  function updatePageInEditingDoc(updated) {
    editingDoc.pages = editingDoc.pages.map(function (p) { return p.id === updated.id ? updated : p; });
    pagesChangedDuringEdit = true;
  }

  function openCropDialog(page) {
    croppingPage = page;
    cropStatus.textContent = '';
    cropDialog.showModal();
    cropImage.onload = function () {
      if (cropper) cropper.destroy();
      cropper = new Cropper(cropImage, { viewMode: 1, autoCropArea: 1, background: false, movable: false, zoomable: false });
    };
    cropImage.src = contentUrl(editingDoc, page);
  }

  function closeCropDialog() {
    if (cropper) {
      cropper.destroy();
      cropper = null;
    }
    cropImage.onload = null;
    cropImage.removeAttribute('src');
    cropDialog.close();
  }

  $('cancelCrop').addEventListener('click', closeCropDialog);

  $('saveCrop').addEventListener('click', function () {
    if (!cropper) return;
    var canvas = cropper.getCroppedCanvas();
    if (!canvas) return;
    // Re-encode in the page's own format when the browser can, so its extension stays right.
    var mime = ['image/png', 'image/webp'].indexOf(croppingPage.mime) !== -1 ? croppingPage.mime : 'image/jpeg';
    cropStatus.textContent = t('saving');
    canvas.toBlob(function (blob) {
      var form = new FormData();
      form.append('file', blob, 'crop');
      api('POST', 'api/documents/' + editingDoc.id + '/pages/' + croppingPage.id + '/crop', form).then(function (page) {
        updatePageInEditingDoc(page);
        closeCropDialog();
        renderEditPages();
      }).catch(function (err) {
        cropStatus.textContent = errorMessage(err);
      });
    }, mime, 0.92);
  });

  function restorePage(page) {
    api('POST', 'api/documents/' + editingDoc.id + '/pages/' + page.id + '/restore').then(function (updated) {
      updatePageInEditingDoc(updated);
      renderEditPages();
    });
  }

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

  function renderManage() {
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

  $('manageBtn').addEventListener('click', function () {
    renderManage();
    manageDialog.showModal();
  });

  $('closeManage').addEventListener('click', function () { manageDialog.close(); });
  $('manageNewSection').addEventListener('click', function () { openSectionDialog(null); });
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

  // --- start ------------------------------------------------------------------------------

  $('uploadBtn').addEventListener('click', function () {
    if (sections.length) openDocumentDialog(null); else openSectionDialog(null);
  });

  loadSettings().catch(function () {});
  refresh();
})();
