const { Plugin, PluginSettingTab, Setting, Notice, requestUrl } = require('obsidian');

const DEFAULT_SETTINGS = {
  serverUrl: 'http://your-server-domain.com',
  apiSecret: '',
  archiveMode: 'daily',
  dailyFolder: 'Daily',
  inboxFile: 'Inbox.md',
  attachmentFolder: 'attachments',
  autoSync: true,
  syncInterval: 60
};

class WeChatObsidianPlugin extends Plugin {
  async onload() {
    await this.loadSettings();

    // 1. 添加左侧功能区图标 (Ribbon Icon)
    this.addRibbonIcon('message-square', '同步微信笔记', () => {
      this.syncNotes(true);
    });

    // 2. 注册命令面板动作 (Ctrl/Cmd + P)
    this.addCommand({
      id: 'sync-wechat-notes',
      name: '立即同步微信笔记到本地',
      callback: () => this.syncNotes(true)
    });

    // 3. 注册设置页面
    this.addSettingTab(new WeChatSyncSettingTab(this.app, this));

    // 4. 自动定时同步计时器
    this.setupAutoSync();

    console.log('WeChat Obsidian Sync Plugin loaded.');
  }

  onunload() {
    if (this.syncTimer) {
      clearInterval(this.syncTimer);
    }
  }

  setupAutoSync() {
    if (this.syncTimer) {
      clearInterval(this.syncTimer);
      this.syncTimer = null;
    }
    if (this.settings.autoSync && this.settings.syncInterval > 0) {
      this.syncTimer = setInterval(() => {
        this.syncNotes(false);
      }, this.settings.syncInterval * 1000);
    }
  }

  async syncNotes(manual = false) {
    if (this.isSyncing) return;
    this.isSyncing = true;

    try {
      const syncUrl = `${this.settings.serverUrl.replace(/\/+$/, '')}/api/sync?secret=${encodeURIComponent(this.settings.apiSecret)}&limit=50`;
      
      const resp = await requestUrl({
        url: syncUrl,
        method: 'GET'
      });

      if (resp.status !== 200 || !resp.json) {
        if (manual) new Notice(`同步失败: 服务器响应异常 (HTTP ${resp.status})`);
        return;
      }

      const notes = resp.json.notes || [];
      if (notes.length === 0) {
        if (manual) new Notice('微信笔记已是最新，暂无新消息');
        return;
      }

      const syncedIds = [];
      for (const note of notes) {
        try {
          await this.processAndAppendNote(note);
          syncedIds.push(note.id);
        } catch (err) {
          console.error('处理单条笔记异常:', err, note);
        }
      }

      // 提交同步确认 (ACK)
      if (syncedIds.length > 0) {
        const ackUrl = `${this.settings.serverUrl.replace(/\/+$/, '')}/api/sync/ack?secret=${encodeURIComponent(this.settings.apiSecret)}`;
        await requestUrl({
          url: ackUrl,
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ids: syncedIds })
        });

        new Notice(`🎉 微信笔记同步完成：已落盘 ${syncedIds.length} 条新笔记！`);
      }
    } catch (err) {
      console.error('同步微信笔记异常:', err);
      if (manual) new Notice(`同步异常: ${err.message || err}`);
    } finally {
      this.isSyncing = false;
    }
  }

  async processAndAppendNote(note) {
    const timestamp = note.create_time ? note.create_time * 1000 : Date.now();
    const d = new Date(timestamp);
    const dateStr = this.formatDate(d);
    const timeStr = this.formatDateTime(d);

    let targetFilePath = '';
    if (this.settings.archiveMode === 'daily') {
      const folderPath = `${this.settings.dailyFolder}/${dateStr}`;
      await this.ensureDirectory(folderPath);
      targetFilePath = `${folderPath}/同步助手_${dateStr}.md`;
    } else {
      const folderPath = this.settings.inboxFile.substring(0, this.settings.inboxFile.lastIndexOf('/'));
      if (folderPath) await this.ensureDirectory(folderPath);
      targetFilePath = this.settings.inboxFile;
    }

    // 1. 如果有图片，下载保存到附件文件夹
    let imageMarkdown = '';
    if (note.media_filename) {
      const imagesFolder = this.settings.attachmentFolder;
      await this.ensureDirectory(imagesFolder);
      const imgLocalPath = `${imagesFolder}/${note.media_filename}`;

      try {
        const imgUrl = `${this.settings.serverUrl.replace(/\/+$/, '')}/api/image/${encodeURIComponent(note.media_filename)}`;
        const imgResp = await requestUrl({ url: imgUrl, method: 'GET' });
        if (imgResp.status === 200) {
          await this.app.vault.adapter.writeBinary(imgLocalPath, imgResp.arrayBuffer);
          imageMarkdown = `\n![[${imgLocalPath}|缩略图]]`;
        }
      } catch (e) {
        console.warn('下载图片附件失败:', e);
      }
    }

    // 2. 构造格式化 Markdown
    const tagsStr = (note.tags || []).join(' ');
    let block = '\n---\n';

    if (note.msg_type === 'link' || note.url) {
      block += `#### ${note.title || '网页收藏'}\n`;
      block += `## 📅 ${timeStr}\n`;
      if (note.url) {
        block += `[${note.title || note.url}](${note.url})\n`;
      }
      if (note.author) {
        block += `**作者**: ${note.author}\n`;
      }
      if (note.tldr) {
        block += `> [!abstract] 💡 AI 核心速读 (100字)\n> ${note.tldr}\n`;
      }
      if (note.key_points && note.key_points.length > 0) {
        block += `> [!tip] 📌 核心要点\n${note.key_points.map(p => `> - ${p}`).join('\n')}\n`;
      }
      if (tagsStr) block += `\n${tagsStr}\n`;
      if (imageMarkdown) block += `${imageMarkdown}\n`;
    } else if (note.msg_type === 'image') {
      block += `#### 🖼️ 图片备忘\n`;
      block += `## 📅 ${timeStr}\n`;
      if (imageMarkdown) block += `${imageMarkdown}\n`;
      if (tagsStr) block += `\n${tagsStr}\n`;
    } else {
      block += `## 📅 ${timeStr}\n`;
      block += `${(note.raw_content || '').trim()}\n`;
      if (tagsStr) block += `\n${tagsStr}\n`;
    }

    if (note.msg_id) {
      block += `<!--wx:${note.msg_id}-->\n`;
    }

    // 3. 追加写入文件 (检查幂等性)
    const exists = await this.app.vault.adapter.exists(targetFilePath);
    if (exists) {
      const currentContent = await this.app.vault.adapter.read(targetFilePath);
      if (note.msg_id && currentContent.includes(`<!--wx:${note.msg_id}-->`)) {
        console.log(`笔记已存在，跳过追加: ${note.msg_id}`);
        return;
      }
      await this.app.vault.adapter.append(targetFilePath, block);
    } else {
      const header = `---\ntags: [微信随手记]\n---\n`;
      await this.app.vault.adapter.write(targetFilePath, header + block);
    }
  }

  async ensureDirectory(path) {
    if (!path) return;
    const exists = await this.app.vault.adapter.exists(path);
    if (!exists) {
      await this.app.vault.adapter.mkdir(path);
    }
  }

  formatDate(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
  }

  formatDateTime(d) {
    const date = this.formatDate(d);
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    const ss = String(d.getSeconds()).padStart(2, '0');
    return `${date} ${hh}:${mm}:${ss}`;
  }

  async loadSettings() {
    this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
  }

  async saveSettings() {
    await this.saveData(this.settings);
    this.setupAutoSync();
  }
}

class WeChatSyncSettingTab extends PluginSettingTab {
  constructor(app, plugin) {
    super(app, plugin);
    this.plugin = plugin;
  }

  display() {
    const { containerEl } = this;
    containerEl.empty();
    containerEl.createEl('h2', { text: '微信 Obsidian 笔记助手设置' });

    new Setting(containerEl)
      .setName('同步服务器 URL')
      .setDesc('部署在云端服务器的地址 (如 http://your-server-domain.com)')
      .addText(text => text
        .setPlaceholder('http://your-server-domain.com')
        .setValue(this.plugin.settings.serverUrl)
        .onChange(async val => {
          this.plugin.settings.serverUrl = val.trim();
          await this.plugin.saveSettings();
        }));

    new Setting(containerEl)
      .setName('同步安全密钥 (API Secret)')
      .setDesc('与云端 config.yaml 中 sync.api_secret 保持一致')
      .addText(text => text
        .setPlaceholder('密钥')
        .setValue(this.plugin.settings.apiSecret)
        .onChange(async val => {
          this.plugin.settings.apiSecret = val.trim();
          await this.plugin.saveSettings();
        }));

    new Setting(containerEl)
      .setName('归档模式')
      .setDesc('按日归档 (Daily Notes) 或单文件集中归档 (Inbox)')
      .addDropdown(drop => drop
        .addOption('daily', '按日归档 (推荐)')
        .addOption('inbox', '单文件归档')
        .setValue(this.plugin.settings.archiveMode)
        .onChange(async val => {
          this.plugin.settings.archiveMode = val;
          await this.plugin.saveSettings();
        }));

    new Setting(containerEl)
      .setName('按日归档目录')
      .setDesc('存放每天笔记的父文件夹')
      .addText(text => text
        .setValue(this.plugin.settings.dailyFolder)
        .onChange(async val => {
          this.plugin.settings.dailyFolder = val.trim();
          await this.plugin.saveSettings();
        }));

    new Setting(containerEl)
      .setName('图片附件保存目录')
      .setDesc('微信下载的图片所存放的目录')
      .addText(text => text
        .setValue(this.plugin.settings.attachmentFolder)
        .onChange(async val => {
          this.plugin.settings.attachmentFolder = val.trim();
          await this.plugin.saveSettings();
        }));

    new Setting(containerEl)
      .setName('自动定时同步')
      .setDesc('在 Obsidian 打开时后台自动定时拉取微信笔记')
      .addToggle(toggle => toggle
        .setValue(this.plugin.settings.autoSync)
        .onChange(async val => {
          this.plugin.settings.autoSync = val;
          await this.plugin.saveSettings();
        }));

    new Setting(containerEl)
      .setName('自动同步间隔 (秒)')
      .setDesc('默认 60 秒')
      .addText(text => text
        .setValue(String(this.plugin.settings.syncInterval))
        .onChange(async val => {
          const num = parseInt(val, 10);
          if (!isNaN(num) && num >= 10) {
            this.plugin.settings.syncInterval = num;
            await this.plugin.saveSettings();
          }
        }));
  }
}

module.exports = WeChatObsidianPlugin;
