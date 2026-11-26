(() => {
  'use strict';
  const dialog = document.createElement('dialog');
  dialog.id = 'modelSettingsDialog';
  dialog.setAttribute('aria-labelledby', 'modelSettingsTitle');
  dialog.setAttribute('aria-describedby', 'modelSettingsDescription');
  dialog.innerHTML = `
    <form id="modelSettingsForm" novalidate>
      <div class="ms-head">
        <div>
          <div class="ms-kicker">WORKSPACE / CONTROL CENTER</div>
          <h2 id="modelSettingsTitle">系统与模型设置</h2>
          <p id="modelSettingsDescription" class="ms-subtitle">统一管理全站模型、推理深度、默认提示词、四应用参数、知乎凭据与研究画像。</p>
        </div>
        <button type="button" class="ms-button ms-icon" id="modelSettingsClose" aria-label="关闭系统设置"><i data-lucide="x" aria-hidden="true"></i></button>
      </div>

      <div class="ms-tabs" role="tablist" aria-label="设置分类">
        <button type="button" class="ms-tab" role="tab" id="tabBtnModel" data-tab="model" aria-selected="true" aria-controls="panelModel">模型与推理<span class="ms-tab-dot" hidden></span></button>
        <button type="button" class="ms-tab" role="tab" id="tabBtnApps" data-tab="apps" aria-selected="false" aria-controls="panelApps">应用参数<span class="ms-tab-dot" hidden></span></button>
        <button type="button" class="ms-tab" role="tab" id="tabBtnProfiles" data-tab="profiles" aria-selected="false" aria-controls="panelProfiles">画像与心法<span class="ms-tab-dot" hidden></span></button>
      </div>

      <datalist id="appModelSuggestions"></datalist>

      <div class="ms-content" id="panelModel" role="tabpanel" aria-labelledby="tabBtnModel">
        <div class="ms-current" aria-label="当前生效配置">
          <div><small>当前通道</small><strong id="modelActiveBackend">正在读取…</strong></div>
          <div><small>默认模型</small><strong id="modelActiveName">—</strong></div>
          <div><small>推理深度 (直连 · Agent)</small><strong id="modelActiveEffort">—</strong></div>
          <div><small>凭据状态</small><strong id="modelKeyState">—</strong></div>
        </div>

        <fieldset class="ms-fieldset"><legend class="ms-legend"><span class="ms-number">01</span>选择模型通道</legend>
          <div class="ms-choices">
            <label class="ms-choice"><input type="radio" name="modelBackend" value="openai-compatible" checked><div><b>OpenAI 兼容 API</b><span>使用 API 地址和 API Key，兼容中转服务。</span></div></label>
            <label class="ms-choice"><input type="radio" name="modelBackend" value="antigravity"><div><b>Antigravity 账号</b><span>使用服务器已导入的 Google OAuth 账号。</span></div></label>
          </div><p class="ms-error" id="modelBackendError" hidden></p>
        </fieldset>

        <fieldset class="ms-fieldset" id="modelApiFields"><legend class="ms-legend"><span class="ms-number">02</span>API 连接</legend><div class="ms-fields">
          <div><label class="ms-label" for="modelBaseUrl">API Base URL</label><input class="ms-input" type="url" id="modelBaseUrl" placeholder="https://api.example.com/v1" autocomplete="url" spellcheck="false" aria-describedby="modelBaseHelp modelBaseError"><p class="ms-help" id="modelBaseHelp">填写公网 HTTPS 接口根地址，通常以 /v1 结尾，不含 /chat/completions。</p><p class="ms-error" id="modelBaseError" hidden></p></div>
          <div><label class="ms-label" for="modelApiKey">API Key</label><div class="ms-secret"><input class="ms-input" type="password" id="modelApiKey" placeholder="留空以保留已保存的密钥" autocomplete="new-password" spellcheck="false" aria-describedby="modelKeyHelp modelKeyError"><button type="button" class="ms-button ms-icon" id="modelToggleKey" aria-label="显示新输入的 API Key" aria-pressed="false"><i data-lucide="eye" aria-hidden="true"></i></button></div><p class="ms-help" id="modelKeyHelp">已保存的密钥不会回传。留空保留；更换 API 地址时需输入对应的新 Key。</p><p class="ms-error" id="modelKeyError" hidden></p></div>
        </div></fieldset>

        <div id="modelAntigravityNotice" class="ms-notice" hidden>沿用服务器已导入的 OAuth 账号，不需要填写 API Key。地区、额度或授权限制可能导致请求失败；验证失败不会切换当前通道。<p id="modelAntigravityState"></p></div>

        <fieldset class="ms-fieldset"><legend class="ms-legend"><span class="ms-number">03</span>默认模型</legend>
          <label class="ms-label" for="modelDefaultName">模型 ID</label>
          <div class="ms-combobox">
            <input class="ms-input" type="text" id="modelDefaultName" placeholder="gemini-3.8-flash" spellcheck="false" autocomplete="off" aria-describedby="modelNameHelp modelNameError" aria-controls="modelListPanel" aria-expanded="false">
            <button type="button" class="ms-button ms-icon" id="modelToggleList" aria-label="展开模型列表" aria-expanded="false" aria-controls="modelListPanel"><i data-lucide="chevron-down" aria-hidden="true"></i></button>
          </div>
          <div id="modelListPanel" class="ms-model-panel" role="listbox" aria-label="可用模型列表" hidden></div>
          <p class="ms-help" id="modelNameHelp">先点击“读取模型列表”获取当前通道可用模型，也可以直接输入完整模型 ID。</p>
          <p class="ms-error" id="modelNameError" hidden></p>
          <div class="ms-actions"><button type="button" class="ms-button" id="modelLoadModels"><i data-lucide="list-filter" aria-hidden="true"></i>读取模型列表</button><button type="button" class="ms-button" id="modelTestConnection"><i data-lucide="activity" aria-hidden="true"></i>测试连接</button></div>
        </fieldset>

        <fieldset class="ms-fieldset"><legend class="ms-legend"><span class="ms-number">04</span>推理深度（Effort）</legend>
          <div class="ms-grid-2">
            <div>
              <label class="ms-label" for="modelDirectEffort">直接请求推理深度（/v1）</label>
              <select class="ms-select" id="modelDirectEffort">
                <option value="minimal">极简 (minimal) — 最快响应</option>
                <option value="low">轻量 (low) — 默认推荐</option>
                <option value="medium">均衡 (medium)</option>
                <option value="high">深度 (high)</option>
              </select>
              <p class="ms-help">用于微信笔记整理、社交雷达评估、普通邮件分析（未显式传参时生效）。</p>
            </div>
            <div>
              <label class="ms-label" for="modelAgentEffort">研究 Agent 推理深度（/agent/v1）</label>
              <select class="ms-select" id="modelAgentEffort">
                <option value="minimal">极简 (minimal)</option>
                <option value="low">轻量 (low)</option>
                <option value="medium">均衡 (medium)</option>
                <option value="high">深度 (high) — 默认推荐</option>
              </select>
              <p class="ms-help">用于 Insight 洞察提炼、追问与 MailAssist 学术论文深度研读。</p>
            </div>
          </div>
        </fieldset>

        <fieldset class="ms-fieldset"><legend class="ms-legend"><span class="ms-number">05</span>默认提示词（System Prompt）</legend>
          <div class="ms-fields">
            <div>
              <label class="ms-label" for="modelDefaultPrompt">全局默认追加提示词（所有通道生效，可选）</label>
              <textarea class="ms-textarea" id="modelDefaultPrompt" rows="3" maxlength="4000" placeholder="例如：回答优先突出第一性原理与硬件/系统定量权衡，语言简洁直击本质。（留空表示不额外追加）" aria-describedby="modelDefaultPromptError"></textarea>
              <p class="ms-error" id="modelDefaultPromptError" hidden></p>
            </div>
            <div>
              <div class="ms-label-row">
                <label class="ms-label" for="modelAgentInstructions">研究 Agent 核心指令（/agent/v1 前置系统提示词）</label>
                <button type="button" class="ms-button ms-btn-sm" id="modelResetAgentPrompt">恢复内置默认指令</button>
              </div>
              <textarea class="ms-textarea" id="modelAgentInstructions" rows="5" maxlength="4000" aria-describedby="modelAgentPromptHelp modelAgentPromptError"></textarea>
              <p class="ms-help" id="modelAgentPromptHelp">控制 Insight 与论文 Agent 如何使用历史检索工具、引用格式与防注入规则；与内置默认一致或留空时均使用系统默认。</p>
              <p class="ms-error" id="modelAgentPromptError" hidden></p>
            </div>
          </div>
        </fieldset>
      </div>

      <div class="ms-content" id="panelApps" role="tabpanel" aria-labelledby="tabBtnApps" hidden>
        <div class="ms-card">
          <div class="ms-card-head">
            <div><h3>知乎共享凭据（SocialRadar + 微信笔记共用）</h3><p class="ms-help">不回传已保存 Cookie；留空则保持当前配置，填入新 Cookie 后保存将同步热更新两个服务。</p></div>
            <div class="ms-card-actions"><span class="ms-inline-badge" id="appZhihuState">检查中…</span><button type="button" class="ms-button ms-btn-sm" id="btnTestZhihuCookie">测试 Cookie</button></div>
          </div>
          <div class="ms-secret">
            <input class="ms-input" type="password" id="appZhihuCookie" placeholder="留空保留当前 Cookie；如需更换请粘贴完整知乎 Cookie（含 z_c0）" autocomplete="off" spellcheck="false">
            <button type="button" class="ms-button ms-icon" id="appToggleZhihuCookie" aria-label="显示知乎 Cookie" aria-pressed="false"><i data-lucide="eye" aria-hidden="true"></i></button>
          </div>
        </div>

        <div class="ms-card" id="cardAppInsight">
          <div class="ms-card-head">
            <div><h3>InsightEngine（洞察引擎 · 1000005）</h3><p class="ms-help">跨信源渐进思考、免打扰时段与推送门槛。</p></div>
            <button type="button" class="ms-button ms-btn-sm" id="btnTriggerInsight">立即提炼</button>
          </div>
          <div class="ms-grid-3">
            <div><label class="ms-label" for="appInsightQuiet">免打扰时段</label><input class="ms-input" id="appInsightQuiet" placeholder="23:00-09:00 或 off"></div>
            <div><label class="ms-label" for="appInsightLookback">回溯小时 (24–720)</label><input class="ms-input" type="number" id="appInsightLookback" min="24" max="720"></div>
            <div><label class="ms-label" for="appInsightInterval">思考周期/小时 (1–168)</label><input class="ms-input" type="number" id="appInsightInterval" min="1" max="168"></div>
            <div><label class="ms-label" for="appInsightScore">推送阈值分 (50–100)</label><input class="ms-input" type="number" id="appInsightScore" min="50" max="100"></div>
            <div><label class="ms-label" for="appInsightModel">使用模型</label><input class="ms-input" id="appInsightModel" list="appModelSuggestions" placeholder="default"></div>
            <label class="ms-check-row"><input type="checkbox" id="appInsightAutoNotify"><span>高价值自动推送</span></label>
          </div>
        </div>

        <div class="ms-card" id="cardAppMail">
          <div class="ms-card-head">
            <div><h3>MailAssist（邮件与学术助手 · 1000002）</h3><p class="ms-help">邮箱轮询周期、论文与事务评分门槛。</p></div>
            <button type="button" class="ms-button ms-btn-sm" id="btnTriggerMail">立即巡检邮箱</button>
          </div>
          <div class="ms-grid-3">
            <div><label class="ms-label" for="appMailQuiet">免打扰时段</label><input class="ms-input" id="appMailQuiet" placeholder="23:00-09:00 或 off"></div>
            <div><label class="ms-label" for="appMailPoll">轮询周期/秒 (30–86400)</label><input class="ms-input" type="number" id="appMailPoll" min="30" max="86400"></div>
            <div><label class="ms-label" for="appMailSinceDays">抓取天数 (1–90)</label><input class="ms-input" type="number" id="appMailSinceDays" min="1" max="90"></div>
            <div><label class="ms-label" for="appMailMaxFetch">单轮上限 (1–50)</label><input class="ms-input" type="number" id="appMailMaxFetch" min="1" max="50"></div>
            <div><label class="ms-label" for="appMailScholarScore">论文阈值分 (0–100)</label><input class="ms-input" type="number" id="appMailScholarScore" min="0" max="100"></div>
            <div><label class="ms-label" for="appMailTaskThreshold">事务重要度 (1–5)</label><input class="ms-input" type="number" id="appMailTaskThreshold" min="1" max="5"></div>
            <div><label class="ms-label" for="appMailModel">使用模型</label><input class="ms-input" id="appMailModel" list="appModelSuggestions" placeholder="default"></div>
          </div>
        </div>

        <div class="ms-card" id="cardAppRadar">
          <div class="ms-card-head">
            <div><h3>SocialRadar（社交前沿雷达 · 1000004）</h3><p class="ms-help">知乎监控账号、巡检频率与价值分门槛。</p></div>
            <button type="button" class="ms-button ms-btn-sm" id="btnTriggerRadar">立即抓取雷达</button>
          </div>
          <div class="ms-grid-3">
            <div><label class="ms-label" for="appRadarQuiet">免打扰时段</label><input class="ms-input" id="appRadarQuiet" placeholder="23:00-09:00 或 off"></div>
            <div><label class="ms-label" for="appRadarInterval">轮询间隔/分 (5–1440)</label><input class="ms-input" type="number" id="appRadarInterval" min="5" max="1440"></div>
            <div><label class="ms-label" for="appRadarDaysBack">回溯天数 (1–90)</label><input class="ms-input" type="number" id="appRadarDaysBack" min="1" max="90"></div>
            <div><label class="ms-label" for="appRadarScore">价值阈值分 (0–100)</label><input class="ms-input" type="number" id="appRadarScore" min="0" max="100"></div>
            <div><label class="ms-label" for="appRadarUserToken">知乎 user_token</label><input class="ms-input" id="appRadarUserToken" placeholder="Bowen"></div>
            <div><label class="ms-label" for="appRadarMaxQuestions">单轮问题数 (1–50)</label><input class="ms-input" type="number" id="appRadarMaxQuestions" min="1" max="50"></div>
            <div><label class="ms-label" for="appRadarModel">使用模型</label><input class="ms-input" id="appRadarModel" list="appModelSuggestions" placeholder="default"></div>
          </div>
          <div class="ms-check-group">
            <label class="ms-check-row"><input type="checkbox" id="appRadarZhihuEnabled"><span>启用知乎抓取</span></label>
            <label class="ms-check-row"><input type="checkbox" id="appRadarMoments"><span>监控关注动态</span></label>
            <label class="ms-check-row"><input type="checkbox" id="appRadarQuestions"><span>监控关注问题</span></label>
          </div>
        </div>

        <div class="ms-card" id="cardAppObsidian">
          <div class="ms-card-head">
            <div><h3>WeChat Obsidian（微信笔记助手 · 1000003）</h3><p class="ms-help">本服务支持保存后即时热更新，无需重启。</p></div>
          </div>
          <div class="ms-grid-3">
            <div><label class="ms-label" for="appObsidianModel">使用模型</label><input class="ms-input" id="appObsidianModel" list="appModelSuggestions" placeholder="default"></div>
            <div><label class="ms-label" for="appObsidianTemp">采样温度 (0.0–2.0)</label><input class="ms-input" type="number" step="0.1" id="appObsidianTemp" min="0" max="2"></div>
            <div><label class="ms-label" for="appObsidianArchiveMode">归档模式</label><select class="ms-select" id="appObsidianArchiveMode"><option value="daily">按日归档 (daily)</option><option value="inbox">单文件 (inbox)</option></select></div>
            <div><label class="ms-label" for="appObsidianFormat">笔记模板</label><select class="ms-select" id="appObsidianFormat"><option value="bullet">列表 (bullet)</option><option value="callout">提示框 (callout)</option><option value="plain">纯文本 (plain)</option></select></div>
            <div><label class="ms-label" for="appObsidianDailyFolder">每日目录</label><input class="ms-input" id="appObsidianDailyFolder"></div>
            <div><label class="ms-label" for="appObsidianInboxFile">Inbox 文件</label><input class="ms-input" id="appObsidianInboxFile"></div>
          </div>
          <div class="ms-check-group">
            <label class="ms-check-row"><input type="checkbox" id="appObsidianLlmEnable"><span>启用 AI 速读与智能标签</span></label>
          </div>
        </div>
      </div>

      <div class="ms-content" id="panelProfiles" role="tabpanel" aria-labelledby="tabBtnProfiles" hidden>
        <div class="ms-card">
          <div class="ms-card-head"><div><h3>MailAssist 学术与论文兴趣画像</h3><p class="ms-help">控制论文相关性评分、关注侧重点与排除主题（每行一条，关键词可用逗号或换行分隔）。</p></div></div>
          <div class="ms-grid-2">
            <div><label class="ms-label" for="profMailTopics">核心研究方向</label><textarea class="ms-textarea" id="profMailTopics" rows="4"></textarea></div>
            <div><label class="ms-label" for="profMailKeywords">强相关会议与关键词</label><textarea class="ms-textarea" id="profMailKeywords" rows="4"></textarea></div>
            <div><label class="ms-label" for="profMailExclude">排除/低优先级领域</label><textarea class="ms-textarea" id="profMailExclude" rows="3"></textarea></div>
            <div><label class="ms-label" for="profMailFocus">速读卡片关注维度</label><textarea class="ms-textarea" id="profMailFocus" rows="3"></textarea></div>
          </div>
          <div class="ms-grid-2" style="margin-top:12px;">
            <div><label class="ms-label" for="profMailLang">速读语言</label><select class="ms-select" id="profMailLang"><option value="zh">中文 (zh)</option><option value="en">English (en)</option></select></div>
          </div>
        </div>

        <div class="ms-card">
          <div class="ms-card-head"><div><h3>SocialRadar 社交价值评估画像</h3><p class="ms-help">控制知乎动态/问答的价值评分标准与降噪过滤规则。</p></div></div>
          <div class="ms-grid-2">
            <div><label class="ms-label" for="profRadarTopics">高价值关注领域</label><textarea class="ms-textarea" id="profRadarTopics" rows="4"></textarea></div>
            <div><label class="ms-label" for="profRadarKeywords">强相关关键词</label><textarea class="ms-textarea" id="profRadarKeywords" rows="4"></textarea></div>
          </div>
          <div style="margin-top:12px;"><label class="ms-label" for="profRadarExclude">严格降噪/排除规则（每行一条）</label><textarea class="ms-textarea" id="profRadarExclude" rows="3"></textarea></div>
          <div class="ms-check-group">
            <label class="ms-check-row"><input type="checkbox" id="profRadarInDepth"><span>偏好深度长文与真实一线实践</span></label>
            <label class="ms-check-row"><input type="checkbox" id="profRadarTradeoffs"><span>偏好架构权衡 (Trade-off) 与 PPA 剖析</span></label>
          </div>
        </div>

        <div class="ms-card">
          <div class="ms-card-head">
            <div><h3>InsightEngine 体系结构研究心法 (architecture_philosophy.yaml)</h3><p class="ms-help">直接注入 InsightAgent 跨源深度碰撞的 System Prompt，保存时校验 YAML 语法。</p></div>
            <span class="ms-inline-badge" id="profPhilosophyCount">0 字</span>
          </div>
          <textarea class="ms-textarea ms-textarea-mono" id="profPhilosophyYaml" rows="12" spellcheck="false"></textarea>
        </div>
      </div>

      <div class="ms-footer">
        <div class="ms-status" id="modelSettingsStatus" role="status" aria-live="polite" aria-atomic="true">配置仅保存在服务器，不保存在浏览器。</div>
        <div class="ms-footer-actions">
          <button type="button" class="ms-button" id="modelSettingsReload">重新加载</button>
          <button type="submit" class="ms-button ms-primary" id="modelSettingsSave">保存模型与推理</button>
        </div>
      </div>
    </form>`;
  document.body.append(dialog);
  const el = id => document.getElementById(id);

  let saved = null;
  let savedApps = null;
  let pending = false;
  let activeTab = 'model';
  const dirtyTabs = { model: false, apps: false, profiles: false };
  let previousFocus = null;
  let generation = 0;
  let busyFocus = null;
  let availableModels = [];
  let listOpen = false;

  const fields = {
    base_url: 'modelBaseUrl',
    api_key: 'modelApiKey',
    default_model: 'modelDefaultName',
    default_system_prompt: 'modelDefaultPrompt',
    agent_instructions: 'modelAgentInstructions',
  };
  const errors = {
    backend: 'modelBackendError',
    base_url: 'modelBaseError',
    api_key: 'modelKeyError',
    default_model: 'modelNameError',
    default_system_prompt: 'modelDefaultPromptError',
    agent_instructions: 'modelAgentPromptError',
  };
  const tabMeta = {
    model: { panel: 'panelModel', btn: 'tabBtnModel', saveLabel: '保存模型与推理' },
    apps: { panel: 'panelApps', btn: 'tabBtnApps', saveLabel: '保存应用参数' },
    profiles: { panel: 'panelProfiles', btn: 'tabBtnProfiles', saveLabel: '保存画像与心法' },
  };

  function status(message, tone = '') {
    el('modelSettingsStatus').textContent = message;
    el('modelSettingsStatus').dataset.tone = tone;
  }
  function anyDirty() {
    return dirtyTabs.model || dirtyTabs.apps || dirtyTabs.profiles;
  }
  function updateDirtyIndicators() {
    for (const [tab, meta] of Object.entries(tabMeta)) {
      const dot = el(meta.btn).querySelector('.ms-tab-dot');
      if (dot) dot.hidden = !dirtyTabs[tab];
    }
  }
  function markDirty(tab, value = true) {
    dirtyTabs[tab] = value;
    updateDirtyIndicators();
  }
  function clearErrors() {
    Object.values(errors).forEach(id => { el(id).hidden = true; el(id).textContent = ''; });
    Object.values(fields).forEach(id => el(id).removeAttribute('aria-invalid'));
  }
  function setPending(value) {
    if (value) busyFocus = document.activeElement;
    pending = value;
    dialog.setAttribute('aria-busy', String(value));
    dialog.querySelectorAll('button,input,select,textarea').forEach(item => {
      item.disabled = value && item.id !== 'modelSettingsClose';
    });
    if (value && busyFocus?.disabled) el('modelSettingsClose').focus();
    if (!value && dialog.open && !dialog.contains(document.activeElement)) el('modelSettingsClose').focus();
    if (!value && busyFocus?.isConnected && !busyFocus.disabled && dialog.contains(busyFocus)) busyFocus.focus();
    el('modelSettingsSave').textContent = value ? '处理中…' : tabMeta[activeTab].saveLabel;
  }
  function switchTab(tab) {
    activeTab = tab;
    setListOpen(false);
    for (const [key, meta] of Object.entries(tabMeta)) {
      const selected = key === tab;
      el(meta.btn).setAttribute('aria-selected', String(selected));
      el(meta.panel).hidden = !selected;
    }
    el('modelSettingsSave').textContent = pending ? '处理中…' : tabMeta[tab].saveLabel;
  }
  function backend() { return dialog.querySelector('input[name="modelBackend"]:checked').value; }
  function showBackend() {
    const native = backend() === 'antigravity';
    el('modelApiFields').hidden = native;
    el('modelAntigravityNotice').hidden = !native;
    el('modelAntigravityState').textContent = saved?.antigravity_configured ? '服务器已配置账号，仍需验证模型请求。' : '服务器未检测到账号，请先通过服务器导入。';
  }
  function renderModelList(filter = '') {
    const panel = el('modelListPanel');
    const currentValue = el('modelDefaultName').value.trim();
    const query = filter.trim().toLowerCase();
    const filtered = query ? availableModels.filter(id => id.toLowerCase().includes(query)) : availableModels;
    if (availableModels.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'ms-model-empty';
      empty.textContent = '暂无模型列表，请点击下方“读取模型列表”获取当前通道可用模型。';
      panel.replaceChildren(empty);
      return;
    }
    if (filtered.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'ms-model-empty';
      empty.textContent = `未匹配到“${filter}”，可直接使用输入的模型 ID，或点击右侧下拉按钮查看全部 ${availableModels.length} 个模型。`;
      panel.replaceChildren(empty);
      return;
    }
    panel.replaceChildren(...filtered.map(id => {
      const option = document.createElement('button');
      option.type = 'button';
      option.className = 'ms-model-option';
      option.setAttribute('role', 'option');
      option.dataset.model = id;
      const selected = id === currentValue;
      option.setAttribute('aria-selected', String(selected));
      const label = document.createElement('span');
      label.textContent = id;
      option.append(label);
      if (selected) {
        const check = document.createElement('span');
        check.className = 'ms-model-check';
        check.textContent = '✓';
        option.append(check);
      }
      return option;
    }));
  }
  function setListOpen(open, filter = '') {
    listOpen = open;
    el('modelListPanel').hidden = !open;
    el('modelToggleList').setAttribute('aria-expanded', String(open));
    el('modelDefaultName').setAttribute('aria-expanded', String(open));
    if (open) renderModelList(filter);
  }
  function updateAppModelDatalist() {
    const unique = ['default', ...availableModels.filter(m => m !== 'default')];
    el('appModelSuggestions').replaceChildren(...unique.map(id => {
      const opt = document.createElement('option');
      opt.value = id;
      return opt;
    }));
  }
  function models(list, { open = false } = {}) {
    availableModels = Array.isArray(list) ? [...new Set(list)] : [];
    updateAppModelDatalist();
    el('modelNameHelp').textContent = availableModels.length > 0
      ? `当前通道已加载 ${availableModels.length} 个可用模型，点击下拉按钮选择，或直接输入搜索。`
      : '先点击“读取模型列表”获取当前通道可用模型，也可以直接输入完整模型 ID。';
    if (open) {
      setListOpen(true, '');
      el('modelListPanel').scrollIntoView({ block: 'nearest' });
    } else if (listOpen) {
      renderModelList('');
    }
  }
  function renderModel(settings) {
    saved = settings;
    dialog.querySelector(`input[name="modelBackend"][value="${settings.backend === 'antigravity' ? 'antigravity' : 'openai-compatible'}"]`).checked = true;
    el('modelActiveBackend').textContent = settings.backend === 'antigravity' ? 'Antigravity OAuth' : 'OpenAI 兼容 API';
    el('modelActiveName').textContent = settings.default_model;
    el('modelActiveEffort').textContent = `${settings.direct_effort || 'low'} · ${settings.agent_effort || 'high'}`;
    el('modelKeyState').textContent = settings.backend === 'antigravity' ? (settings.antigravity_configured ? '账号已配置' : '账号未配置') : (settings.api_key_configured ? '密钥已配置 · 不回显' : '尚未配置密钥');
    el('modelBaseUrl').value = settings.base_url || '';
    el('modelDefaultName').value = settings.default_model;
    el('modelDirectEffort').value = settings.direct_effort || 'low';
    el('modelAgentEffort').value = settings.agent_effort || 'high';
    el('modelDefaultPrompt').value = settings.default_system_prompt || '';
    el('modelAgentInstructions').value = settings.agent_instructions || settings.default_agent_instructions || '';
    el('modelApiKey').value = '';
    el('modelApiKey').type = 'password';
    el('modelToggleKey').setAttribute('aria-pressed', 'false');
    el('modelToggleKey').setAttribute('aria-label', '显示新输入的 API Key');
    setListOpen(false);
    models(settings.models || []);
    showBackend();
    markDirty('model', false);
    clearErrors();
  }
  function renderApps(data) {
    savedApps = data;
    const apps = data.apps || {};
    const ins = apps.insight || {};
    el('appInsightQuiet').value = ins.quiet_hours ?? '23:00-09:00';
    el('appInsightLookback').value = ins.lookback_hours ?? 72;
    el('appInsightInterval').value = ins.run_interval_hours ?? 6;
    el('appInsightScore').value = ins.min_insight_score ?? 80;
    el('appInsightModel').value = ins.llm_model ?? 'default';
    el('appInsightAutoNotify').checked = Boolean(ins.auto_notify_threshold);

    const mail = apps.mail || {};
    el('appMailQuiet').value = mail.quiet_hours ?? '23:00-09:00';
    el('appMailPoll').value = mail.poll_interval ?? 180;
    el('appMailSinceDays').value = mail.since_days ?? 7;
    el('appMailMaxFetch').value = mail.max_fetch_emails_per_round ?? 10;
    el('appMailScholarScore').value = mail.scholar_score_threshold ?? 65;
    el('appMailTaskThreshold').value = mail.task_importance_threshold ?? 3;
    el('appMailModel').value = mail.llm_model ?? 'default';

    const radar = apps.radar || {};
    el('appRadarQuiet').value = radar.quiet_hours ?? '23:00-09:00';
    el('appRadarInterval').value = radar.base_interval_minutes ?? 20;
    el('appRadarDaysBack').value = radar.max_days_back ?? 7;
    el('appRadarScore').value = radar.min_value_score ?? 70;
    el('appRadarUserToken').value = radar.zhihu_user_token ?? '';
    el('appRadarMaxQuestions').value = radar.zhihu_max_questions_per_round ?? 8;
    el('appRadarModel').value = radar.llm_model ?? 'default';
    el('appRadarZhihuEnabled').checked = Boolean(radar.zhihu_enabled);
    el('appRadarMoments').checked = Boolean(radar.zhihu_check_moments);
    el('appRadarQuestions').checked = Boolean(radar.zhihu_check_questions);

    const obs = apps.obsidian || {};
    el('appObsidianModel').value = obs.llm_model ?? 'default';
    el('appObsidianTemp').value = obs.llm_temperature ?? 0.2;
    el('appObsidianArchiveMode').value = obs.archive_mode ?? 'daily';
    el('appObsidianFormat').value = obs.format_template ?? 'bullet';
    el('appObsidianDailyFolder').value = obs.daily_folder ?? '';
    el('appObsidianInboxFile').value = obs.inbox_file ?? '';
    el('appObsidianLlmEnable').checked = Boolean(obs.llm_enable);

    const zh = apps.zhihu || {};
    el('appZhihuCookie').value = '';
    el('appZhihuCookie').type = 'password';
    el('appToggleZhihuCookie').setAttribute('aria-pressed', 'false');
    el('appZhihuState').textContent = zh.cookie_configured ? `已配置 (${zh.cookie_length || 0} 字)` : '未配置';
    markDirty('apps', false);
  }
  function renderProfiles(data) {
    const profiles = data.profiles || {};
    const mail = profiles.mail || {};
    el('profMailTopics').value = (mail.research_topics || []).join('\n');
    el('profMailKeywords').value = (mail.keywords || []).join(', ');
    el('profMailExclude').value = (mail.exclude_topics || []).join('\n');
    el('profMailFocus').value = (mail.focus_aspects || []).join('\n');
    el('profMailLang').value = mail.language || 'zh';

    const radar = profiles.radar || {};
    el('profRadarTopics').value = (radar.target_topics || []).join('\n');
    el('profRadarKeywords').value = (radar.keywords || []).join(', ');
    el('profRadarExclude').value = (radar.exclude_patterns || []).join('\n');
    el('profRadarInDepth').checked = Boolean(radar.reward_in_depth_insights);
    el('profRadarTradeoffs').checked = Boolean(radar.reward_architectural_tradeoffs);

    const phil = profiles.insight_philosophy || {};
    el('profPhilosophyYaml').value = phil.yaml_text || '';
    el('profPhilosophyCount').textContent = `${(phil.yaml_text || '').length} 字`;
    markDirty('profiles', false);
  }
  function modelPayload() {
    if (!saved) throw new Error('请先重新加载当前配置');
    const rawAgentPrompt = el('modelAgentInstructions').value.trim();
    const defaultAgentPrompt = (saved.default_agent_instructions || '').trim();
    const input = {
      revision: saved.revision,
      backend: backend(),
      base_url: el('modelBaseUrl').value.trim(),
      default_model: el('modelDefaultName').value.trim(),
      direct_effort: el('modelDirectEffort').value,
      agent_effort: el('modelAgentEffort').value,
      default_system_prompt: el('modelDefaultPrompt').value.trim(),
      agent_instructions: rawAgentPrompt === defaultAgentPrompt ? '' : rawAgentPrompt,
    };
    if (input.backend === 'openai-compatible' && el('modelApiKey').value.trim()) input.api_key = el('modelApiKey').value.trim();
    return input;
  }
  function parseLines(text) {
    return text.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
  }
  function parseKeywords(text) {
    return text.split(/[\r\n,，]+/).map(s => s.trim()).filter(Boolean);
  }
  function appsPayload() {
    const out = {
      insight: {
        quiet_hours: el('appInsightQuiet').value.trim(),
        lookback_hours: Number(el('appInsightLookback').value),
        run_interval_hours: Number(el('appInsightInterval').value),
        min_insight_score: Number(el('appInsightScore').value),
        llm_model: el('appInsightModel').value.trim() || 'default',
        auto_notify_threshold: el('appInsightAutoNotify').checked,
      },
      mail: {
        quiet_hours: el('appMailQuiet').value.trim(),
        poll_interval: Number(el('appMailPoll').value),
        since_days: Number(el('appMailSinceDays').value),
        max_fetch_emails_per_round: Number(el('appMailMaxFetch').value),
        scholar_score_threshold: Number(el('appMailScholarScore').value),
        task_importance_threshold: Number(el('appMailTaskThreshold').value),
        llm_model: el('appMailModel').value.trim() || 'default',
      },
      radar: {
        quiet_hours: el('appRadarQuiet').value.trim(),
        base_interval_minutes: Number(el('appRadarInterval').value),
        max_days_back: Number(el('appRadarDaysBack').value),
        min_value_score: Number(el('appRadarScore').value),
        zhihu_user_token: el('appRadarUserToken').value.trim(),
        zhihu_max_questions_per_round: Number(el('appRadarMaxQuestions').value),
        llm_model: el('appRadarModel').value.trim() || 'default',
        zhihu_enabled: el('appRadarZhihuEnabled').checked,
        zhihu_check_moments: el('appRadarMoments').checked,
        zhihu_check_questions: el('appRadarQuestions').checked,
      },
      obsidian: {
        llm_model: el('appObsidianModel').value.trim() || 'default',
        llm_temperature: Number(el('appObsidianTemp').value),
        archive_mode: el('appObsidianArchiveMode').value,
        format_template: el('appObsidianFormat').value,
        daily_folder: el('appObsidianDailyFolder').value.trim(),
        inbox_file: el('appObsidianInboxFile').value.trim(),
        llm_enable: el('appObsidianLlmEnable').checked,
      },
    };
    const cookie = el('appZhihuCookie').value.trim();
    if (cookie) out.zhihu = { cookie };
    return out;
  }
  function profilesPayload() {
    return {
      mail: {
        research_topics: parseLines(el('profMailTopics').value),
        keywords: parseKeywords(el('profMailKeywords').value),
        exclude_topics: parseLines(el('profMailExclude').value),
        focus_aspects: parseLines(el('profMailFocus').value),
        language: el('profMailLang').value,
      },
      radar: {
        target_topics: parseLines(el('profRadarTopics').value),
        keywords: parseKeywords(el('profRadarKeywords').value),
        exclude_patterns: parseLines(el('profRadarExclude').value),
        reward_in_depth_insights: el('profRadarInDepth').checked,
        reward_architectural_tradeoffs: el('profRadarTradeoffs').checked,
      },
      insight_philosophy: {
        yaml_text: el('profPhilosophyYaml').value,
      },
    };
  }
  function showError(error) {
    const message = typeof error.message === 'string' ? error.message : '操作失败，请重试';
    status(message, 'error');
    if (errors[error.field]) {
      el(errors[error.field]).textContent = message;
      el(errors[error.field]).hidden = false;
      if (fields[error.field]) { el(fields[error.field]).setAttribute('aria-invalid', 'true'); el(fields[error.field]).focus(); }
    }
  }
  async function apiRequest(url, data) {
    const result = await apiFetch(url, data ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) } : {});
    if (result.code !== 0) {
      const error = new Error(typeof result.error === 'string' ? result.error : '配置服务返回错误，请稍后重试');
      error.field = result.field;
      throw error;
    }
    return result;
  }
  async function loadAll({ tabOnly = null } = {}) {
    const run = ++generation;
    setPending(true);
    status('正在读取服务器当前配置…');
    try {
      if (!tabOnly || tabOnly === 'model') {
        const [modelRes, appRes] = await Promise.all([
          apiRequest('/api/dashboard/model-settings'),
          tabOnly ? Promise.resolve(null) : apiRequest('/api/dashboard/app-settings'),
        ]);
        if (run !== generation || !dialog.open) return;
        renderModel(modelRes.settings);
        if (appRes) {
          renderApps(appRes);
          renderProfiles(appRes);
        }
        status(modelRes.settings.configuration_error ? `当前模型通道不可用：${modelRes.settings.configuration_error}。请修改配置后重新验证。` : '配置已加载。密钥与 Cookie 不会回显，可直接测试或修改后保存。', modelRes.settings.configuration_error ? 'error' : '');
      } else {
        const appRes = await apiRequest('/api/dashboard/app-settings');
        if (run !== generation || !dialog.open) return;
        if (tabOnly === 'apps') renderApps(appRes);
        if (tabOnly === 'profiles') renderProfiles(appRes);
        status('配置已重新加载。');
      }
    } catch (error) {
      if (run === generation && dialog.open) showError(error);
    } finally {
      if (run === generation) setPending(false);
    }
  }
  function close() {
    if (pending) { status('正在处理请求，请等待完成后关闭。'); return; }
    if (anyDirty() && !confirm('有尚未保存的配置修改，确认放弃？')) return;
    dialog.close();
  }
  el('modelSettingsBtn').addEventListener('click', async () => {
    if (!state.token) { showAuthModal('请先登录后管理工作台设置'); return; }
    previousFocus = document.activeElement;
    switchTab('model');
    dialog.showModal();
    document.body.style.overflow = 'hidden';
    if (window.lucide) lucide.createIcons();
    el('modelSettingsClose').focus();
    await loadAll();
  });
  dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
  dialog.addEventListener('close', () => {
    generation++;
    saved = null;
    savedApps = null;
    availableModels = [];
    setListOpen(false);
    markDirty('model', false);
    markDirty('apps', false);
    markDirty('profiles', false);
    el('modelApiKey').value = '';
    el('modelApiKey').type = 'password';
    el('appZhihuCookie').value = '';
    el('appZhihuCookie').type = 'password';
    document.body.style.overflow = '';
    previousFocus?.focus();
  });
  el('modelSettingsClose').addEventListener('click', close);
  el('modelSettingsReload').addEventListener('click', () => {
    if (!dirtyTabs[activeTab] || confirm('重新加载将放弃当前标签页未保存的修改，继续？')) {
      loadAll({ tabOnly: activeTab });
    }
  });
  Object.values(tabMeta).forEach(meta => {
    el(meta.btn).addEventListener('click', () => {
      if (!pending) switchTab(el(meta.btn).dataset.tab);
    });
  });
  function syncChannelModels() {
    setListOpen(false);
    const sameChannel = saved && backend() === saved.backend && (backend() === 'antigravity' || el('modelBaseUrl').value.trim().replace(/\/+$/, '') === (saved.base_url || '').replace(/\/+$/, ''));
    models(sameChannel ? (saved.models || []) : []);
  }
  el('panelModel').querySelectorAll('input,select,textarea').forEach(node => {
    node.addEventListener('input', () => {
      markDirty('model', true);
      clearErrors();
      showBackend();
      if (node.name === 'modelBackend' || node.id === 'modelBaseUrl') syncChannelModels();
      if (node.id === 'modelDefaultName' && availableModels.length > 0) setListOpen(true, el('modelDefaultName').value.trim());
      status('模型与推理设置尚未保存。');
    });
  });
  el('panelApps').querySelectorAll('input,select').forEach(node => {
    node.addEventListener('input', () => {
      markDirty('apps', true);
      status('应用参数尚未保存。');
    });
  });
  el('panelProfiles').querySelectorAll('textarea,select,input').forEach(node => {
    node.addEventListener('input', () => {
      markDirty('profiles', true);
      if (node.id === 'profPhilosophyYaml') el('profPhilosophyCount').textContent = `${node.value.length} 字`;
      status('画像与心法尚未保存。');
    });
  });
  el('modelResetAgentPrompt').addEventListener('click', () => {
    el('modelAgentInstructions').value = saved?.default_agent_instructions || '';
    markDirty('model', true);
    clearErrors();
    status('已恢复为系统内置默认研究 Agent 指令（保存后生效）。');
  });
  el('modelToggleList').addEventListener('click', () => setListOpen(!listOpen, ''));
  el('modelDefaultName').addEventListener('click', () => {
    if (!listOpen && availableModels.length > 0) setListOpen(true, '');
  });
  function handleListEscape(event) {
    if (event.key === 'Escape' && listOpen) {
      event.preventDefault();
      event.stopPropagation();
      setListOpen(false);
      el('modelDefaultName').focus();
    }
  }
  el('modelDefaultName').addEventListener('keydown', handleListEscape);
  el('modelListPanel').addEventListener('keydown', handleListEscape);
  el('modelListPanel').addEventListener('click', event => {
    const option = event.target.closest('.ms-model-option');
    if (!option) return;
    el('modelDefaultName').value = option.dataset.model;
    markDirty('model', true);
    clearErrors();
    setListOpen(false);
    status('已选择模型 ' + option.dataset.model + '（尚未保存）。');
    el('modelDefaultName').focus();
  });
  dialog.addEventListener('click', event => {
    if (listOpen && !event.target.closest('.ms-combobox') && !event.target.closest('#modelListPanel')) setListOpen(false);
  });
  el('modelToggleKey').addEventListener('click', () => {
    const visible = el('modelApiKey').type === 'password';
    el('modelApiKey').type = visible ? 'text' : 'password';
    el('modelToggleKey').setAttribute('aria-pressed', String(visible));
    el('modelToggleKey').setAttribute('aria-label', visible ? '隐藏新输入的 API Key' : '显示新输入的 API Key');
  });
  el('appToggleZhihuCookie').addEventListener('click', () => {
    const visible = el('appZhihuCookie').type === 'password';
    el('appZhihuCookie').type = visible ? 'text' : 'password';
    el('appToggleZhihuCookie').setAttribute('aria-pressed', String(visible));
  });
  async function performModel(action) {
    clearErrors();
    let input;
    try { input = modelPayload(); } catch (error) { showError(error); return; }
    setPending(true);
    status(action === 'models' ? '正在读取候选通道的模型目录…' : action === 'test' ? '正在发送一条简短模型请求，请稍候…' : '正在验证并保存模型与推理配置…');
    try {
      const result = await apiRequest('/api/dashboard/model-settings/' + action, input);
      if (action === 'models') {
        models(result.models, { open: true });
        status(`已读取 ${result.models.length} 个模型，请在下方列表中直接点击选择。`, 'success');
      } else if (action === 'test') {
        status(`连接成功 · ${result.test.model} · ${(result.test.latency_ms / 1000).toFixed(2)} 秒。当前配置未修改。`, 'success');
      } else {
        renderModel(result.settings);
        status('模型、推理深度与默认提示词已保存并热生效。', 'success');
      }
    } catch (error) {
      showError(error);
    } finally {
      setPending(false);
      const invalid = dialog.querySelector('[aria-invalid=true]');
      if (invalid) invalid.focus();
    }
  }
  async function saveApps() {
    setPending(true);
    status('正在校验并保存应用参数，变更的服务将自动重启…');
    try {
      const res = await apiRequest('/api/dashboard/app-settings/apps', appsPayload());
      renderApps(res);
      const extra = res.restarted?.length ? `已自动重启：${res.restarted.join(', ')}` : '已热生效';
      const warn = res.restart_errors?.length ? `（重启提醒：${res.restart_errors.join('; ')}）` : '';
      status(`应用参数保存成功 · ${extra}${warn}`, 'success');
    } catch (error) {
      showError(error);
    } finally {
      setPending(false);
    }
  }
  async function saveProfiles() {
    setPending(true);
    status('正在校验 YAML 并保存画像与研究心法…');
    try {
      const res = await apiRequest('/api/dashboard/app-settings/profiles', profilesPayload());
      renderProfiles(res);
      const extra = res.restarted?.length ? `已同步重启：${res.restarted.join(', ')}` : '已保存';
      status(`画像与研究心法保存成功 · ${extra}`, 'success');
    } catch (error) {
      showError(error);
    } finally {
      setPending(false);
    }
  }
  async function triggerAction(action, extra = {}) {
    setPending(true);
    status('正在向服务发送操作请求…');
    try {
      const res = await apiRequest('/api/dashboard/app-settings/action', { action, ...extra });
      status(res.message || '操作已完成', res.ok ? 'success' : 'error');
    } catch (error) {
      showError(error);
    } finally {
      setPending(false);
    }
  }

  el('modelLoadModels').addEventListener('click', () => performModel('models'));
  el('modelTestConnection').addEventListener('click', () => performModel('test'));
  el('btnTestZhihuCookie').addEventListener('click', () => triggerAction('test_zhihu_cookie', { cookie: el('appZhihuCookie').value.trim() }));
  el('btnTriggerInsight').addEventListener('click', () => triggerAction('trigger_insight'));
  el('btnTriggerMail').addEventListener('click', () => triggerAction('trigger_mail_check'));
  el('btnTriggerRadar').addEventListener('click', () => triggerAction('trigger_radar_check'));
  el('modelSettingsForm').addEventListener('submit', event => {
    event.preventDefault();
    if (pending) return;
    if (activeTab === 'model') performModel('save');
    else if (activeTab === 'apps') saveApps();
    else saveProfiles();
  });
})();
