// UI strings. The language is picked from the browser's preferences: the first
// one that's Portuguese or English wins, and anything else falls back to English.
// A string can be a template ("{name}") or a function of its variables (plurals).
var I18N = (function () {
  var STRINGS = {
    en: {
      new: 'New',
      select: 'Select',
      cancel: 'Cancel',
      save: 'Save',
      upload: 'Upload',
      close: 'Close',
      edit: 'Edit',
      delete: 'Delete',
      download: 'Download',
      openFile: 'Open',
      add: 'Add',
      encryption: 'Encryption',
      settings: 'Settings',
      theme: 'Theme',
      'theme.midnight': 'Midnight',
      'theme.forest': 'Forest',
      'theme.plum': 'Plum',
      'theme.paper': 'Paper',
      'theme.sky': 'Sky',
      'theme.rose': 'Rose',
      sections: 'Sections',
      tags: 'Tags',
      allTags: 'All',
      newSection: 'New section',
      editSection: 'Edit section',
      name: 'Name',
      sectionNamePlaceholder: 'e.g. Alice, Rex, Car, House',
      icon: 'Icon',
      folderHint: 'Folder in the volume: {folder}/',
      newTag: 'New tag',
      renameTag: 'Rename tag',
      noTags: 'No tags yet. Tags work across sections, e.g. Health, Taxes, Travel.',
      docCount: function (v) { return v.n === 1 ? '1 document' : v.n + ' documents'; },
      loginTitle: 'Sign in',
      username: 'Username',
      password: 'Password',
      login: 'Sign in',
      logout: 'Sign out',
      signingIn: 'Signing in...',
      volume: 'Volume',
      scan: 'Scan for new files',
      scanHelp: 'Files and folders you added to the volume by hand become documents and sections.',
      scanning: 'Scanning...',
      scanResult: function (v) {
        if (!v.documents && !v.sections) return 'Nothing new found.';
        var docs = v.documents === 1 ? '1 document' : v.documents + ' documents';
        var secs = v.sections === 1 ? '1 new section' : v.sections + ' new sections';
        return v.sections ? 'Added ' + docs + ' and ' + secs + '.' : 'Added ' + docs + '.';
      },
      moveUp: 'Move up',
      moveDown: 'Move down',
      newDocument: 'New document',
      editDocument: 'Edit document',
      title: 'Title',
      titlePlaceholder: 'e.g. Passport, Vaccination card...',
      date: 'Date',
      section: 'Section',
      pages: 'Pages',
      takePhoto: 'Take photo',
      addFiles: 'Add files',
      crop: 'Crop',
      restoreOriginal: 'Restore original',
      removePage: 'Remove',
      cropImage: 'Crop image',
      saveCrop: 'Save crop',
      noPreview: 'No preview for this file type.',
      selectedCount: function (v) { return v.n + ' selected'; },
      uploading: 'Uploading...',
      saving: 'Saving...',
      converting: 'Converting files...',
      welcomeTitle: 'Your papers, your way',
      welcomeText: 'Create a section for each person, pet, car or house: anything you keep documents for. ' +
        'Each section is a folder in your documents volume, and each document a file named after it.',
      emptySection: 'No documents here yet.',
      emptyTag: 'No documents with this tag here.',
      confirmDeleteDocument: 'Delete this document? This can\'t be undone.',
      confirmDeleteSection: 'Delete the section "{name}"?',
      confirmDeleteTag: 'Delete the tag "{name}"? It will be taken off every document.',
      encryptionOn: 'Encryption is on',
      encryptionOff: 'Encryption is off',
      encryptionOnHelp: 'Documents are stored encrypted in the volume, so they can\'t be browsed there (or read ' +
        'from your backups) without the key. Decrypting puts every file back in its section\'s folder, ' +
        'named after its title.',
      encryptionOffHelp: 'Documents are ordinary files in the volume, in a folder per section and named after ' +
        'their titles, so you can browse and copy them directly (and so can anyone with access to the ' +
        'volume or its backups). Encrypting moves every file into an encrypted vault, readable only by the app.',
      encryptionUnavailableHelp: 'To encrypt your documents, set ENCRYPTION_KEY in your docker compose file and ' +
        'restart Papelada. See the README for how to generate a key.',
      encryptAll: 'Encrypt everything',
      decryptAll: 'Decrypt everything',
      convertedCount: function (v) {
        if (!v.n) return 'No file needed converting.';
        return v.n === 1 ? '1 file converted.' : v.n + ' files converted.';
      },
      needPages: 'Add at least one page.',
      'errors.generic': 'Something went wrong. Please try again.',
      'errors.section_exists': 'There\'s already a section with this name.',
      'errors.tag_exists': 'There\'s already a tag with this name.',
      'errors.section_not_empty': 'Move or delete this section\'s documents first.',
      'errors.name_required': 'Give it a name.',
      'errors.title_required': 'Give the document a title.',
      'errors.too_long': 'That name is too long.',
      'errors.invalid_date': 'Choose a date.',
      'errors.file_in_the_way': 'There\'s a file in the way at {path}. Move it out of the volume and try again.',
      'errors.encryption_unavailable': 'Encryption needs ENCRYPTION_KEY to be set.',
      'errors.scan_needs_plain': 'Scanning only works while encryption is off.',
      'errors.invalid_credentials': 'Wrong username or password.',
      'errors.too_many_attempts': function (v) {
        var minutes = Math.max(1, Math.ceil((v.retry_after || 60) / 60));
        return 'Too many attempts. Try again in ' + (minutes === 1 ? '1 minute.' : minutes + ' minutes.');
      }
    },
    'pt-BR': {
      new: 'Novo',
      select: 'Selecionar',
      cancel: 'Cancelar',
      save: 'Salvar',
      upload: 'Enviar',
      close: 'Fechar',
      edit: 'Editar',
      delete: 'Excluir',
      download: 'Baixar',
      openFile: 'Abrir',
      add: 'Adicionar',
      encryption: 'Criptografia',
      settings: 'Ajustes',
      theme: 'Tema',
      'theme.midnight': 'Meia-noite',
      'theme.forest': 'Floresta',
      'theme.plum': 'Ameixa',
      'theme.paper': 'Papel',
      'theme.sky': 'Céu',
      'theme.rose': 'Rosa',
      sections: 'Seções',
      tags: 'Tags',
      allTags: 'Todos',
      newSection: 'Nova seção',
      editSection: 'Editar seção',
      name: 'Nome',
      sectionNamePlaceholder: 'Ex.: Ana, Rex, Carro, Casa',
      icon: 'Ícone',
      folderHint: 'Pasta no volume: {folder}/',
      newTag: 'Nova tag',
      renameTag: 'Renomear tag',
      noTags: 'Nenhuma tag ainda. As tags valem para todas as seções, ex.: Saúde, Impostos, Viagem.',
      docCount: function (v) { return v.n === 1 ? '1 documento' : v.n + ' documentos'; },
      loginTitle: 'Entrar',
      username: 'Usuário',
      password: 'Senha',
      login: 'Entrar',
      logout: 'Sair',
      signingIn: 'Entrando...',
      volume: 'Volume',
      scan: 'Procurar arquivos novos',
      scanHelp: 'Arquivos e pastas que você colocou no volume à mão viram documentos e seções.',
      scanning: 'Procurando...',
      scanResult: function (v) {
        if (!v.documents && !v.sections) return 'Nada de novo encontrado.';
        var docs = v.documents === 1 ? '1 documento' : v.documents + ' documentos';
        var secs = v.sections === 1 ? '1 seção nova' : v.sections + ' seções novas';
        return v.sections ? docs + ' e ' + secs + ' adicionados.' : docs + (v.documents === 1 ? ' adicionado.' : ' adicionados.');
      },
      moveUp: 'Mover para cima',
      moveDown: 'Mover para baixo',
      newDocument: 'Novo documento',
      editDocument: 'Editar documento',
      title: 'Nome',
      titlePlaceholder: 'Ex.: RG, Carteira de vacinação...',
      date: 'Data',
      section: 'Seção',
      pages: 'Páginas',
      takePhoto: 'Tirar foto',
      addFiles: 'Adicionar arquivos',
      crop: 'Cortar',
      restoreOriginal: 'Restaurar original',
      removePage: 'Remover',
      cropImage: 'Cortar imagem',
      saveCrop: 'Salvar corte',
      noPreview: 'Sem pré-visualização para este tipo de arquivo.',
      selectedCount: function (v) { return v.n === 1 ? '1 selecionado' : v.n + ' selecionados'; },
      uploading: 'Enviando...',
      saving: 'Salvando...',
      converting: 'Convertendo arquivos...',
      welcomeTitle: 'Sua papelada, do seu jeito',
      welcomeText: 'Crie uma seção para cada pessoa, pet, carro ou casa: tudo de que você guarda documentos. ' +
        'Cada seção é uma pasta no volume de documentos, e cada documento um arquivo com o nome dele.',
      emptySection: 'Nenhum documento aqui ainda.',
      emptyTag: 'Nenhum documento com esta tag aqui.',
      confirmDeleteDocument: 'Excluir este documento? Essa ação não pode ser desfeita.',
      confirmDeleteSection: 'Excluir a seção "{name}"?',
      confirmDeleteTag: 'Excluir a tag "{name}"? Ela será removida de todos os documentos.',
      encryptionOn: 'Criptografia ativada',
      encryptionOff: 'Criptografia desativada',
      encryptionOnHelp: 'Os documentos ficam criptografados no volume, então não dá para navegar por eles lá ' +
        '(nem lê-los nos backups) sem a chave. Descriptografar devolve cada arquivo à pasta da sua seção, ' +
        'com o nome do documento.',
      encryptionOffHelp: 'Os documentos são arquivos comuns no volume, numa pasta por seção e com o nome de cada ' +
        'documento, então dá para navegar por eles e copiá-los diretamente (assim como qualquer pessoa com ' +
        'acesso ao volume ou aos backups). Criptografar move todos os arquivos para um cofre criptografado, que ' +
        'só o app consegue ler.',
      encryptionUnavailableHelp: 'Para criptografar os documentos, defina ENCRYPTION_KEY no docker compose e ' +
        'reinicie o Papelada. O README explica como gerar uma chave.',
      encryptAll: 'Criptografar tudo',
      decryptAll: 'Descriptografar tudo',
      convertedCount: function (v) {
        if (!v.n) return 'Nenhum arquivo precisou ser convertido.';
        return v.n === 1 ? '1 arquivo convertido.' : v.n + ' arquivos convertidos.';
      },
      needPages: 'Adicione ao menos uma página.',
      'errors.generic': 'Algo deu errado. Tente novamente.',
      'errors.section_exists': 'Já existe uma seção com esse nome.',
      'errors.tag_exists': 'Já existe uma tag com esse nome.',
      'errors.section_not_empty': 'Mova ou exclua os documentos desta seção primeiro.',
      'errors.name_required': 'Dê um nome.',
      'errors.title_required': 'Dê um nome ao documento.',
      'errors.too_long': 'Esse nome é longo demais.',
      'errors.invalid_date': 'Escolha uma data.',
      'errors.file_in_the_way': 'Há um arquivo no caminho em {path}. Tire-o do volume e tente novamente.',
      'errors.encryption_unavailable': 'A criptografia precisa de ENCRYPTION_KEY definida.',
      'errors.scan_needs_plain': 'A busca só funciona com a criptografia desativada.',
      'errors.invalid_credentials': 'Usuário ou senha incorretos.',
      'errors.too_many_attempts': function (v) {
        var minutes = Math.max(1, Math.ceil((v.retry_after || 60) / 60));
        return 'Muitas tentativas. Tente novamente em ' + (minutes === 1 ? '1 minuto.' : minutes + ' minutos.');
      }
    }
  };

  function pickLanguage() {
    var preferred = navigator.languages && navigator.languages.length ? navigator.languages : [navigator.language || 'en'];
    for (var i = 0; i < preferred.length; i++) {
      var lang = String(preferred[i]).toLowerCase();
      if (lang.indexOf('pt') === 0) return 'pt-BR';
      if (lang.indexOf('en') === 0) return 'en';
    }
    return 'en';
  }

  var lang = pickLanguage();

  function t(key, vars) {
    var value = STRINGS[lang][key];
    if (value === undefined) value = STRINGS.en[key];
    if (value === undefined) return key;
    vars = vars || {};
    if (typeof value === 'function') return value(vars);
    return value.replace(/\{(\w+)\}/g, function (_, name) { return vars[name] != null ? vars[name] : ''; });
  }

  function has(key) {
    return STRINGS.en[key] !== undefined;
  }

  // Fills in elements marked with data-i18n (text), data-i18n-placeholder and
  // data-i18n-title (title + aria-label, for icon-only buttons).
  function apply(root) {
    document.documentElement.lang = lang;
    root.querySelectorAll('[data-i18n]').forEach(function (el) {
      el.textContent = t(el.getAttribute('data-i18n'));
    });
    root.querySelectorAll('[data-i18n-placeholder]').forEach(function (el) {
      el.placeholder = t(el.getAttribute('data-i18n-placeholder'));
    });
    root.querySelectorAll('[data-i18n-title]').forEach(function (el) {
      var text = t(el.getAttribute('data-i18n-title'));
      el.title = text;
      el.setAttribute('aria-label', text);
    });
  }

  return { lang: lang, t: t, has: has, apply: apply };
})();
