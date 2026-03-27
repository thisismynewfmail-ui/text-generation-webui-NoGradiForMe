/* ═══════════════════════════════════════════════════════════
   SHODAN-NET  //  Text Generation Interface  //  App Logic
   ═══════════════════════════════════════════════════════════ */

const App = {
  // ── State ──
  settings: {},
  currentTab: 'chat',
  chatHistory: { internal: [], visible: [], metadata: {} },
  uniqueId: null,
  isGenerating: false,
  chatSocket: null,
  notebookSocket: null,
  _saveTimer: null,

  // ══════════════════════════════════════════════
  //  INIT
  // ══════════════════════════════════════════════
  async init() {
    this.bindTabs();
    this.bindSliders();
    this.bindEvents();
    await this.loadStatus();
    await Promise.all([
      this.loadModelList(),
      this.loadCharacterList(),
      this.loadPresetList(),
      this.loadTemplateList(),
      this.loadGrammarList(),
      this.loadChatStyleList(),
      this.loadUserList(),
      this.loadLoRAList(),
      this.loadPromptList(),
      this.loadImageModelList(),
      this.loadExtensionList(),
    ]);
    this.connectChatSocket();
    this.connectNotebookSocket();
    this.loadPastChats();
    this.notify('System online. Welcome to SHODAN-NET.', 'info');
  },

  // ══════════════════════════════════════════════
  //  API HELPER
  // ══════════════════════════════════════════════
  async api(method, url, data) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (data) opts.body = JSON.stringify(data);
    try {
      const r = await fetch(url, opts);
      return await r.json();
    } catch (e) {
      console.error('API error:', e);
      this.notify('Connection error: ' + e.message, 'error');
      return null;
    }
  },

  // ══════════════════════════════════════════════
  //  TAB MANAGEMENT
  // ══════════════════════════════════════════════
  bindTabs() {
    document.querySelectorAll('.nav-btn').forEach(btn => {
      btn.addEventListener('click', () => this.switchTab(btn.dataset.tab));
    });
  },

  switchTab(tab) {
    this.currentTab = tab;
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    const panel = document.getElementById('tab-' + tab);
    if (panel) panel.classList.add('active');
    const btn = document.querySelector(`.nav-btn[data-tab="${tab}"]`);
    if (btn) btn.classList.add('active');
  },

  // ══════════════════════════════════════════════
  //  SLIDER BINDING
  // ══════════════════════════════════════════════
  bindSliders() {
    document.querySelectorAll('.slider-row input[type="range"]').forEach(slider => {
      const valSpan = slider.nextElementSibling;
      if (valSpan && valSpan.classList.contains('slider-val')) {
        valSpan.textContent = slider.value;
        slider.addEventListener('input', () => {
          valSpan.textContent = parseFloat(slider.value).toFixed(slider.step.includes('.') ? (slider.step.split('.')[1] || '').length : 0);
          this.debounceSave();
        });
      }
    });
  },

  // ══════════════════════════════════════════════
  //  EVENT BINDING
  // ══════════════════════════════════════════════
  bindEvents() {
    // Chat
    const $=id=>document.getElementById(id);
    $('btn-send').addEventListener('click', () => this.sendMessage());
    $('chat-input').addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this.sendMessage(); }
    });
    $('btn-stop-chat').addEventListener('click', () => this.stopGeneration());
    $('btn-regenerate').addEventListener('click', () => this.chatAction('regenerate'));
    $('btn-continue').addEventListener('click', () => this.chatAction('continue'));
    $('btn-remove-last').addEventListener('click', () => this.removeLastMessage());
    $('btn-impersonate').addEventListener('click', () => this.chatAction('impersonate'));
    $('btn-new-chat').addEventListener('click', () => this.newChat());

    // Notebook
    $('btn-generate-notebook').addEventListener('click', () => this.generateNotebook());
    $('btn-continue-notebook').addEventListener('click', () => this.continueNotebook());
    $('btn-stop-notebook').addEventListener('click', () => this.stopGeneration());

    // Model
    $('btn-load-model').addEventListener('click', () => this.loadModel());
    $('btn-unload-model').addEventListener('click', () => this.unloadModel());
    $('btn-refresh-models').addEventListener('click', () => this.loadModelList());
    $('btn-load-lora').addEventListener('click', () => this.loadLoRA());

    // Character
    $('btn-refresh-chars').addEventListener('click', () => this.loadCharacterList());
    $('character_menu').addEventListener('change', e => this.loadCharacter(e.target.value));
    $('btn-save-char').addEventListener('click', () => this.saveCharacter());
    $('btn-delete-char').addEventListener('click', () => this.deleteCharacter());
    $('btn-load-template').addEventListener('click', () => this.loadTemplate());

    // Presets
    $('btn-load-preset').addEventListener('click', () => this.loadPreset());
    $('btn-save-preset').addEventListener('click', () => this.savePreset());

    // Notebook prompts
    $('prompt_menu-notebook').addEventListener('change', e => this.loadNotebookPrompt(e.target.value));

    // Image generation
    $('btn-generate-image').addEventListener('click', () => this.generateImage());
    $('btn-load-image-model').addEventListener('click', () => this.loadImageModel());
    $('image_llm_variations').addEventListener('change', e => {
      $('image_llm_variations_prompt').classList.toggle('hidden', !e.target.checked);
    });

    // Session
    $('btn-save-settings').addEventListener('click', () => this.saveAllSettings());

    // Grammar file selection
    $('grammar_file').addEventListener('change', e => this.loadGrammar(e.target.value));

    // Mode change
    $('mode').addEventListener('change', () => this.debounceSave());

    // Auto-save on input changes
    document.querySelectorAll('.ss2-input, .ss2-textarea, .ss2-select, input[type="checkbox"]').forEach(el => {
      el.addEventListener('change', () => this.debounceSave());
    });

    // Chat search
    $('search-chat').addEventListener('input', () => this.loadPastChats());
  },

  // ══════════════════════════════════════════════
  //  STATUS & SETTINGS
  // ══════════════════════════════════════════════
  async loadStatus() {
    const data = await this.api('GET', '/api/status');
    if (!data) return;
    this.settings = data.settings || {};
    this.applySettingsToUI(this.settings);
    this.updateModelStatus(data.model);
  },

  applySettingsToUI(s) {
    Object.entries(s).forEach(([key, val]) => {
      const el = document.getElementById(key);
      if (!el) return;
      if (el.type === 'checkbox') el.checked = !!val;
      else if (el.type === 'range') {
        el.value = val;
        const valSpan = el.nextElementSibling;
        if (valSpan && valSpan.classList.contains('slider-val'))
          valSpan.textContent = val;
      }
      else el.value = val ?? '';
    });
  },

  gatherSettings() {
    const s = {};
    const fields = [
      'temperature','dynatemp_low','dynatemp_high','dynatemp_exponent',
      'smoothing_factor','smoothing_curve','top_p','top_k','min_p',
      'top_n_sigma','typical_p','xtc_threshold','xtc_probability',
      'epsilon_cutoff','eta_cutoff','tfs','top_a','adaptive_target','adaptive_decay',
      'dry_multiplier','dry_allowed_length','dry_base','repetition_penalty',
      'frequency_penalty','presence_penalty','encoder_repetition_penalty',
      'no_repeat_ngram_size','repetition_penalty_range',
      'penalty_alpha','guidance_scale','mirostat_mode','mirostat_tau','mirostat_eta',
      'max_new_tokens','prompt_lookup_num_tokens','max_tokens_second',
      'truncation_length','seed',
      'do_sample','dynamic_temperature','temperature_last','auto_max_new_tokens',
      'ban_eos_token','add_bos_token','enable_thinking','skip_special_tokens',
      'stream','static_cache','enable_web_search',
      'reasoning_effort','mode',
      'sampler_priority','custom_stopping_strings','custom_token_bans',
      'negative_prompt','dry_sequence_breakers','grammar_string',
      'name1','name2','context','greeting','user_bio','custom_system_message',
      'instruction_template_str','chat_template_str','chat-instruct_command','chat_style',
      'start_with','show_two_notebook_columns','paste_to_attachment','include_past_attachments',
    ];
    fields.forEach(key => {
      const el = document.getElementById(key);
      if (!el) return;
      if (el.type === 'checkbox') s[key] = el.checked;
      else if (el.type === 'range' || el.type === 'number') s[key] = parseFloat(el.value);
      else s[key] = el.value;
    });
    s.character_menu = document.getElementById('character_menu')?.value || '';
    s.user_menu = document.getElementById('user_menu')?.value || '';
    return s;
  },

  debounceSave() {
    clearTimeout(this._saveTimer);
    this._saveTimer = setTimeout(() => {
      const s = this.gatherSettings();
      this.api('POST', '/api/settings', s);
    }, 1500);
  },

  async saveAllSettings() {
    const s = this.gatherSettings();
    await this.api('POST', '/api/settings', s);
    this.notify('Settings saved.', 'success');
  },

  updateModelStatus(info) {
    const dot = document.getElementById('model-dot');
    const name = document.getElementById('model-name-display');
    const infoDiv = document.getElementById('model-info');
    if (info && info.is_loaded) {
      dot.classList.add('loaded');
      name.textContent = info.model_name;
      if (infoDiv) infoDiv.textContent = `Model: ${info.model_name}\nLoader: ${info.loader || 'N/A'}\nContext: ${info.truncation_length}\nMultimodal: ${info.is_multimodal}`;
    } else {
      dot.classList.remove('loaded');
      name.textContent = 'No model loaded';
      if (infoDiv) infoDiv.textContent = 'No model loaded.';
    }
  },

  // ══════════════════════════════════════════════
  //  WEBSOCKET
  // ══════════════════════════════════════════════
  connectChatSocket() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    this.chatSocket = new WebSocket(`${proto}://${location.host}/api/ws/chat`);
    this.chatSocket.onmessage = e => this.handleChatMessage(JSON.parse(e.data));
    this.chatSocket.onclose = () => setTimeout(() => this.connectChatSocket(), 3000);
    this.chatSocket.onerror = () => {};
  },

  connectNotebookSocket() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    this.notebookSocket = new WebSocket(`${proto}://${location.host}/api/ws/notebook`);
    this.notebookSocket.onmessage = e => this.handleNotebookMessage(JSON.parse(e.data));
    this.notebookSocket.onclose = () => setTimeout(() => this.connectNotebookSocket(), 3000);
    this.notebookSocket.onerror = () => {};
  },

  handleChatMessage(msg) {
    if (msg.type === 'stream') {
      if (msg.history) {
        this.chatHistory = msg.history;
        this.renderChatMessages(msg.history);
      }
    } else if (msg.type === 'done') {
      this.setGenerating(false);
      if (msg.history) {
        this.chatHistory = msg.history;
        this.renderChatMessages(msg.history);
      }
      this.loadPastChats();
    } else if (msg.type === 'error') {
      this.setGenerating(false);
      this.notify('Error: ' + msg.error, 'error');
    } else if (msg.type === 'stopped') {
      this.setGenerating(false);
    }
  },

  handleNotebookMessage(msg) {
    const ta = document.getElementById('textbox-notebook');
    if (msg.type === 'stream') {
      ta.value = msg.text || '';
    } else if (msg.type === 'done') {
      this.setGenerating(false);
      ta.value = msg.text || '';
    } else if (msg.type === 'error') {
      this.setGenerating(false);
      this.notify('Error: ' + msg.error, 'error');
    } else if (msg.type === 'stopped') {
      this.setGenerating(false);
    }
  },

  // ══════════════════════════════════════════════
  //  CHAT FUNCTIONS
  // ══════════════════════════════════════════════
  sendMessage() {
    const input = document.getElementById('chat-input');
    const text = input.value.trim();
    if (!text || this.isGenerating) return;
    input.value = '';
    this.setGenerating(true);

    if (this.chatSocket && this.chatSocket.readyState === WebSocket.OPEN) {
      this.chatSocket.send(JSON.stringify({
        action: 'send',
        text: text,
        params: { ...this.gatherSettings(), unique_id: this.uniqueId }
      }));
    }
  },

  chatAction(action) {
    if (this.isGenerating && action !== 'stop') return;
    this.setGenerating(true);
    if (this.chatSocket && this.chatSocket.readyState === WebSocket.OPEN) {
      this.chatSocket.send(JSON.stringify({
        action: action,
        text: '',
        params: { ...this.gatherSettings(), unique_id: this.uniqueId }
      }));
    }
  },

  async removeLastMessage() {
    if (this.chatHistory.visible.length === 0) return;
    this.chatHistory.visible.pop();
    this.chatHistory.internal.pop();
    this.renderChatMessages(this.chatHistory);
    // Save
    if (this.uniqueId) {
      const s = this.gatherSettings();
      // We'd need a save endpoint; for now just re-render
    }
  },

  async newChat() {
    const data = await this.api('POST', '/api/chat/new');
    if (data && data.history) {
      this.chatHistory = data.history;
      this.uniqueId = data.unique_id || null;
      this.renderChatMessages(data.history);
      this.loadPastChats();
    }
  },

  stopGeneration() {
    this.api('POST', '/api/chat/stop');
    if (this.chatSocket && this.chatSocket.readyState === WebSocket.OPEN) {
      this.chatSocket.send(JSON.stringify({ action: 'stop' }));
    }
    if (this.notebookSocket && this.notebookSocket.readyState === WebSocket.OPEN) {
      this.notebookSocket.send(JSON.stringify({ action: 'stop' }));
    }
    this.setGenerating(false);
  },

  async loadPastChats() {
    const data = await this.api('GET', '/api/chat/histories');
    if (!data || !data.histories) return;
    const list = document.getElementById('chat-list');
    const search = (document.getElementById('search-chat')?.value || '').toLowerCase();

    list.innerHTML = '';
    data.histories.forEach(([label, id]) => {
      if (search && !label.toLowerCase().includes(search) && !id.toLowerCase().includes(search)) return;
      const div = document.createElement('div');
      div.className = 'chat-list-item' + (id === this.uniqueId ? ' active' : '');
      div.textContent = label || id;
      div.title = id;
      div.addEventListener('click', () => this.loadChatHistory(id));
      list.appendChild(div);
    });

    // Auto-select first if none selected
    if (!this.uniqueId && data.histories.length > 0) {
      this.loadChatHistory(data.histories[0][1]);
    }
  },

  async loadChatHistory(uid) {
    this.uniqueId = uid;
    const data = await this.api('GET', `/api/chat/history/${encodeURIComponent(uid)}`);
    if (data && data.history) {
      this.chatHistory = data.history;
      this.renderChatMessages(data.history);
    }
    // Highlight active
    document.querySelectorAll('.chat-list-item').forEach(el => {
      el.classList.toggle('active', el.title === uid);
    });
  },

  renderChatMessages(history) {
    const container = document.getElementById('chat-messages');
    if (!history || !history.visible || history.visible.length === 0) {
      container.innerHTML = '<div style="text-align:center;color:var(--text-dim);padding:40px">No messages yet. Type something to begin.</div>';
      return;
    }
    const name1 = document.getElementById('name1')?.value || 'You';
    const name2 = document.getElementById('name2')?.value || 'AI';
    let html = '';
    history.visible.forEach(([user, bot], i) => {
      if (user && user !== '<|BEGIN-VISIBLE-CHAT|>') {
        html += `<div class="chat-message user"><div class="msg-name">${this.esc(name1)}</div>${this.renderMd(user)}</div>`;
      }
      if (bot) {
        html += `<div class="chat-message assistant"><div class="msg-name">${this.esc(name2)}</div>${this.renderMd(bot)}</div>`;
      }
    });
    container.innerHTML = html;
    container.scrollTop = container.scrollHeight;
  },

  // Simple markdown render
  renderMd(text) {
    if (!text) return '';
    let s = this.esc(text);
    // Code blocks
    s = s.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
    // Inline code
    s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
    // Bold
    s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // Italic
    s = s.replace(/\*(.+?)\*/g, '<em>$1</em>');
    // Links
    s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
    // Line breaks
    s = s.replace(/\n/g, '<br>');
    return s;
  },

  esc(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  },

  // ══════════════════════════════════════════════
  //  NOTEBOOK FUNCTIONS
  // ══════════════════════════════════════════════
  generateNotebook() {
    const ta = document.getElementById('textbox-notebook');
    if (this.isGenerating) return;
    this.setGenerating(true);
    if (this.notebookSocket && this.notebookSocket.readyState === WebSocket.OPEN) {
      this.notebookSocket.send(JSON.stringify({
        action: 'generate',
        text: ta.value,
        params: this.gatherSettings()
      }));
    }
  },

  continueNotebook() {
    this.generateNotebook(); // Same action, server handles continuation
  },

  async loadNotebookPrompt(name) {
    const data = await this.api('GET', `/api/prompts/${encodeURIComponent(name)}`);
    if (data && data.text !== undefined) {
      document.getElementById('textbox-notebook').value = data.text;
    }
  },

  // ══════════════════════════════════════════════
  //  MODEL FUNCTIONS
  // ══════════════════════════════════════════════
  async loadModelList() {
    const data = await this.api('GET', '/api/models/list');
    if (!data) return;
    this.populateSelect('model_menu', data.models, data.current);
  },

  async loadModel() {
    const model = document.getElementById('model_menu').value;
    const loader = document.getElementById('loader').value;
    if (!model) return;
    this.notify('Loading model: ' + model, 'info');
    this.setGenerating(true);
    const data = await this.api('POST', '/api/models/load', { model_name: model, loader });
    this.setGenerating(false);
    if (data && data.model) {
      this.updateModelStatus(data.model);
      this.notify('Model loaded successfully.', 'success');
    } else {
      this.notify('Failed to load model: ' + (data?.error || 'unknown'), 'error');
    }
  },

  async unloadModel() {
    const data = await this.api('POST', '/api/models/unload');
    if (data) {
      this.updateModelStatus(data.model);
      this.notify('Model unloaded.', 'info');
    }
  },

  // ══════════════════════════════════════════════
  //  CHARACTER FUNCTIONS
  // ══════════════════════════════════════════════
  async loadCharacterList() {
    const data = await this.api('GET', '/api/characters/list');
    if (!data) return;
    this.populateSelect('character_menu', data.characters, data.current);
    if (data.current) this.loadCharacter(data.current);
  },

  async loadCharacter(name) {
    if (!name) return;
    const data = await this.api('GET', `/api/characters/${encodeURIComponent(name)}`);
    if (!data || data.error) return;
    const setVal = (id, v) => { const el = document.getElementById(id); if (el) el.value = v || ''; };
    setVal('name1', data.name1);
    setVal('name2', data.name2);
    setVal('context', data.context);
    setVal('greeting', data.greeting);
    this.debounceSave();
  },

  async saveCharacter() {
    const name = document.getElementById('name2')?.value || 'MyChar';
    await this.api('POST', '/api/characters/save', {
      name, name1: document.getElementById('name1')?.value,
      name2: name, context: document.getElementById('context')?.value,
      greeting: document.getElementById('greeting')?.value,
    });
    this.notify('Character saved.', 'success');
    this.loadCharacterList();
  },

  async deleteCharacter() {
    const name = document.getElementById('character_menu')?.value;
    if (!name || !confirm('Delete character: ' + name + '?')) return;
    await this.api('POST', '/api/characters/delete', { name });
    this.notify('Character deleted.', 'info');
    this.loadCharacterList();
  },

  // ══════════════════════════════════════════════
  //  PRESET FUNCTIONS
  // ══════════════════════════════════════════════
  async loadPresetList() {
    const data = await this.api('GET', '/api/presets/list');
    if (!data) return;
    this.populateSelect('preset_menu', data.presets, data.current);
  },

  async loadPreset() {
    const name = document.getElementById('preset_menu')?.value;
    if (!name) return;
    const data = await this.api('POST', '/api/presets/load', { name });
    if (data && data.preset) {
      this.applySettingsToUI(data.preset);
      this.notify('Preset loaded: ' + name, 'success');
    }
  },

  async savePreset() {
    const name = prompt('Preset name:');
    if (!name) return;
    const s = this.gatherSettings();
    await this.api('POST', '/api/presets/save', { name, ...s });
    this.notify('Preset saved.', 'success');
    this.loadPresetList();
  },

  // ══════════════════════════════════════════════
  //  TEMPLATE / GRAMMAR / MISC LISTS
  // ══════════════════════════════════════════════
  async loadTemplateList() {
    const data = await this.api('GET', '/api/templates/list');
    if (data) this.populateSelect('instruction_template_menu', data.templates);
  },

  async loadTemplate() {
    const name = document.getElementById('instruction_template_menu')?.value;
    if (!name || name === 'None') return;
    const data = await this.api('GET', `/api/templates/${encodeURIComponent(name)}`);
    if (data && data.instruction_template) {
      document.getElementById('instruction_template_str').value = data.instruction_template;
    }
  },

  async loadGrammarList() {
    const data = await this.api('GET', '/api/grammars/list');
    if (data) this.populateSelect('grammar_file', data.grammars);
  },

  async loadGrammar(name) {
    if (!name || name === 'None') { document.getElementById('grammar_string').value = ''; return; }
    const data = await this.api('GET', `/api/grammars/${encodeURIComponent(name)}`);
    if (data && data.content) document.getElementById('grammar_string').value = data.content;
  },

  async loadChatStyleList() {
    const data = await this.api('GET', '/api/chat-styles/list');
    if (data) this.populateSelect('chat_style', data.styles, this.settings.chat_style);
  },

  async loadUserList() {
    const data = await this.api('GET', '/api/users/list');
    if (data) this.populateSelect('user_menu', data.users, this.settings.user);
  },

  async loadLoRAList() {
    const data = await this.api('GET', '/api/loras/list');
    if (data) this.populateSelect('lora_menu', data.loras);
  },

  async loadLoRA() {
    const name = document.getElementById('lora_menu')?.value;
    if (!name || name === 'None') return;
    const data = await this.api('POST', '/api/loras/load', { names: [name] });
    if (data) this.notify('LoRA applied.', 'success');
  },

  async loadPromptList() {
    const data = await this.api('GET', '/api/prompts/list');
    if (data) this.populateSelect('prompt_menu-notebook', data.prompts, this.settings['prompt-notebook']);
  },

  async loadImageModelList() {
    const data = await this.api('GET', '/api/image-models/list');
    if (data) this.populateSelect('image_model_menu', data.models, data.current);
  },

  async loadExtensionList() {
    const data = await this.api('GET', '/api/extensions/list');
    if (!data) return;
    const container = document.getElementById('extensions-list');
    container.innerHTML = '';
    data.available.forEach(name => {
      const label = document.createElement('label');
      label.className = 'ss2-checkbox';
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = data.active.includes(name);
      cb.addEventListener('change', () => this.api('POST', '/api/extensions/toggle', { name, enable: cb.checked }));
      label.appendChild(cb);
      label.appendChild(document.createTextNode(' ' + name));
      container.appendChild(label);
    });
  },

  // ══════════════════════════════════════════════
  //  IMAGE GENERATION
  // ══════════════════════════════════════════════
  async generateImage() {
    const prompt = document.getElementById('image_prompt')?.value;
    if (!prompt) return;
    this.setGenerating(true);
    this.notify('Generating image...', 'info');
    const data = await this.api('POST', '/api/images/generate', {
      prompt,
      negative_prompt: document.getElementById('image_neg_prompt')?.value || '',
      width: parseInt(document.getElementById('image_width')?.value || 1024),
      height: parseInt(document.getElementById('image_height')?.value || 1024),
      steps: parseInt(document.getElementById('image_steps')?.value || 9),
      cfg_scale: parseFloat(document.getElementById('image_cfg_scale')?.value || 0),
      seed: parseInt(document.getElementById('image_seed')?.value || -1),
    });
    this.setGenerating(false);
    if (data && data.images) {
      const gallery = document.getElementById('image-gallery');
      gallery.innerHTML = '';
      data.images.forEach(src => {
        const img = document.createElement('img');
        img.src = src;
        gallery.appendChild(img);
      });
      this.notify('Image generated.', 'success');
    } else {
      this.notify('Image generation failed: ' + (data?.error || 'unknown'), 'error');
    }
  },

  async loadImageModel() {
    const name = document.getElementById('image_model_menu')?.value;
    if (!name || name === 'None') return;
    this.notify('Loading image model...', 'info');
    const data = await this.api('POST', '/api/images/load-model', {
      model_name: name,
      dtype: document.getElementById('image_dtype')?.value,
      attn_backend: document.getElementById('image_attn_backend')?.value,
      cpu_offload: document.getElementById('image_cpu_offload')?.checked,
      compile: document.getElementById('image_compile')?.checked,
      quant: document.getElementById('image_quant')?.value,
    });
    if (data && data.status === 'ok') this.notify('Image model loaded.', 'success');
    else this.notify('Failed: ' + (data?.error || 'unknown'), 'error');
  },

  // ══════════════════════════════════════════════
  //  UI HELPERS
  // ══════════════════════════════════════════════
  setGenerating(state) {
    this.isGenerating = state;
    document.getElementById('gen-indicator').classList.toggle('active', state);
    document.getElementById('btn-send').disabled = state;
    document.getElementById('status-gen').textContent = state ? 'GENERATING...' : '';
  },

  populateSelect(id, options, selected) {
    const el = document.getElementById(id);
    if (!el) return;
    el.innerHTML = '';
    (options || []).forEach(opt => {
      const o = document.createElement('option');
      o.value = opt;
      o.textContent = opt;
      if (opt === selected) o.selected = true;
      el.appendChild(o);
    });
  },

  notify(msg, type = 'info') {
    const container = document.getElementById('notifications');
    const div = document.createElement('div');
    div.className = 'notification ' + type;
    div.textContent = msg;
    container.appendChild(div);
    setTimeout(() => div.remove(), 4000);
  },
};

// ── Boot ──
document.addEventListener('DOMContentLoaded', () => App.init());
