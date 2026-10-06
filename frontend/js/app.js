/* ===================================================
   非油报表助手 - 前端主逻辑
   M3 紫色主题 + SVG 图标 + 首页全屏 + 工作区行程栏
   =================================================== */

const API_BASE = '';
let appInfo = null;

// ===== SVG 图标系统 (Material Symbols Rounded) =====
const ICONS = {
    home: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z"/></svg>',
    description: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z"/></svg>',
    analytics: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zM9 17H7v-7h2v7zm4 0h-2V7h2v10zm4 0h-2v-4h2v4z"/></svg>',
    store: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M18.36 9l.6 3h5.04l-2.4-8h-15.6L3.6 9l.6-2.28L4.8 9h13.56zM5 11h14v9H5v-9zm-3 0v2c0 1.1.9 2 2 2s2-.9 2-2v-2H2zm17 0v2c0 1.1.9 2 2 2s2-.9 2-2v-2h-4zM9 14h6v2H9z"/></svg>',
    settings: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z"/></svg>',
    history: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M13 3c-4.97 0-9 4.03-9 9H1l3.89 3.89.07.14L9 12H6c0-3.87 3.13-7 7-7s7 3.13 7 7-3.13 7-7 7c-1.93 0-3.68-.79-4.94-2.06l-1.42 1.42C8.27 19.99 10.51 21 13 21c4.97 0 9-4.03 9-9s-4.03-9-9-9zm-1 5v5l4.28 2.54.72-1.21-3.5-2.08V8H12z"/></svg>',
    info: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>',
    upload: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M9 16h6v-6h4l-7-7-7 7h4zm-4 2h14v2H5z"/></svg>',
    cloud_upload: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M19.35 10.04C18.67 6.59 15.64 4 12 4 9.11 4 6.6 5.64 5.35 8.04 2.34 8.36 0 10.91 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96zM14 13v4h-4v-4H7l5-5 5 5h-3z"/></svg>',
    check: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>',
    check_circle: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>',
    edit: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>',
    play: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>',
    download: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>',
    arrow_back: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z"/></svg>',
    arrow_forward: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M12 4l-1.41 1.41L16.17 11H4v2h12.17l-5.58 5.59L12 20l8-8z"/></svg>',
    error: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>',
    refresh: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg>',
    add: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg>',
    delete: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>',
    tune: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M3 17v2h6v-2H3zM3 5v2h10V5H3zm10 16v-2h8v-2h-8v-2h-2v6h2zM7 9v2H3v2h4v2h2V9H7zm14 4v-2H11v2h10zm-6-4h2V7h4V5h-4V3h-2v6z"/></svg>',
    visibility: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z"/></svg>',
    folder: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/></svg>',
    file: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z"/></svg>',
    image: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M21 19V5c0-1.1-.9-2-2-2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2zM8.5 13.5l2.5 3.01L14.5 12l4.5 6H5l3.5-4.5z"/></svg>',
    zap: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M7 2v11h3v9l7-12h-4l4-8z"/></svg>',
    table_chart: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M10 10h4v4h-4zm0 6h4v4h-4zm6-12h-4v4h4zm-6 0H6v4h4zm6 12h4v4h-4zm0-6h4v4h-4z"/></svg>',
    local_gas_station: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M19.77 7.23l.01-.01-3.72-3.72L15 4.56l2.11 2.11c-.94.36-1.61 1.27-1.61 2.33 0 1.38 1.12 2.5 2.5 2.5.36 0 .69-.08 1-.21v7.21c0 .55-.45 1-1 1s-1-.45-1-1V14c0-1.1-.9-2-2-2h-1V5c0-1.1-.9-2-2-2H6c-1.1 0-2 .9-2 2v16h10v-7.5h1.5v5c0 1.38 1.12 2.5 2.5 2.5s2.5-1.12 2.5-2.5V9c0-.69-.28-1.32-.73-1.77zM12 10H6V5h6v5z"/></svg>',
    receipt_long: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M19 5v14H5V5h14m0-2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-2 6H7v2h10v-2zm0 4H7v2h10v-2zM7 9h10V7H7v2z"/></svg>'
};

// ===== API 调用 =====
async function api(path, options = {}) {
    const resp = await fetch(API_BASE + path, options);
    if (!resp.ok && resp.status !== 400) throw new Error(`API ${path}: ${resp.status}`);
    return resp.json();
}
async function apiUpload(path, formData) {
    const resp = await fetch(API_BASE + path, { method: 'POST', body: formData });
    return resp.json();
}
async function apiPost(path, data) {
    return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
}

// ===== 初始化 =====
async function init() {
    try {
        appInfo = await api('/api/app/info');
        renderHome();
    } catch (e) {
        showSnackbar('后端连接失败: ' + e.message, 'error');
    }
}

// ===================================================
// 首页（全屏，无侧栏）
// ===================================================
function renderHome() {
    const reports = appInfo?.reports || [];
    const now = new Date();
    const reportCards = reports.map(r => {
        const isActive = r.status === 'active';
        const route = getRouteById(r.id);
        const icon = getReportIcon(r.id);
        return `
            <div class="report-card ${isActive ? '' : 'disabled'}" onclick="${isActive ? `enterWorkspace('${route}')` : ''}">
                <div class="report-card-top">
                    <div class="report-card-icon">${icon}</div>
                    <div style="flex-grow:1;">
                        <div class="report-card-name">${r.name}</div>
                        <span class="chip ${isActive ? 'success' : ''}" style="margin-top:6px;">${isActive ? '可用' : '待开发'}</span>
                    </div>
                </div>
                <div class="report-card-desc">${r.description}</div>
                ${isActive ? `<button class="btn btn-tonal w-full" onclick="event.stopPropagation(); enterWorkspace('${route}')">进入报表 ${ICONS.arrow_forward}</button>` : ''}
            </div>
        `;
    }).join('');

    document.getElementById('app').innerHTML = `
        <div class="view home-view">
            <div class="home-topbar">
                <div class="home-app-logo">非</div>
                <div class="home-app-name">非油报表助手</div>
                <div class="home-app-ver">v${appInfo?.version || '0.1.0'} · 中国石化河南鹤壁石油分公司</div>
            </div>
            <div class="home-content">
                <div class="home-hero">
                    <h1>非油品报表自动化助手</h1>
                    <p>上传导出数据，一键生成日报报表。支持多报表入口扩展、跨月目标维护、轻油销量更新等全流程管理。</p>
                    <div class="home-hero-chips">
                        <span class="chip-trans">报表日期: ${appInfo?.report_date || now.toISOString().slice(0,10)}</span>
                        <span class="chip-trans">日报已就绪</span>
                        <span class="chip-trans">10 步自动处理</span>
                    </div>
                </div>
                <div class="home-section-title">${ICONS.table_chart} 报表入口</div>
                <div class="report-grid">${reportCards}</div>
                <div class="home-section-title">${ICONS.zap} 快速开始</div>
                <div class="card">
                    <div class="card-header">
                        <div class="card-icon-box">${ICONS.cloud_upload}</div>
                        <div style="flex-grow:1;">
                            <div class="card-title">非油日报制作流程</div>
                            <div class="card-subtitle">4 个阶段，约 10 秒完成</div>
                        </div>
                    </div>
                    <div style="display:flex; gap:16px; flex-wrap:wrap;">
                        <div style="flex:1; min-width:180px; padding:16px; background:var(--md-surface-container); border-radius:var(--shape-md);">
                            <div style="font-weight:600; margin-bottom:4px;">① 上传数据</div>
                            <div style="font-size:13px; color:var(--md-on-surface-variant);">一次选择 6 张导出表，自动识别</div>
                        </div>
                        <div style="flex:1; min-width:180px; padding:16px; background:var(--md-surface-container); border-radius:var(--shape-md);">
                            <div style="font-weight:600; margin-bottom:4px;">② 确认调整</div>
                            <div style="font-size:13px; color:var(--md-on-surface-variant);">输入手动调整数据（可选）</div>
                        </div>
                        <div style="flex:1; min-width:180px; padding:16px; background:var(--md-surface-container); border-radius:var(--shape-md);">
                            <div style="font-weight:600; margin-bottom:4px;">③ 自动处理</div>
                            <div style="font-size:13px; color:var(--md-on-surface-variant);">10 步流程自动执行</div>
                        </div>
                        <div style="flex:1; min-width:180px; padding:16px; background:var(--md-surface-container); border-radius:var(--shape-md);">
                            <div style="font-weight:600; margin-bottom:4px;">④ 输出文件</div>
                            <div style="font-size:13px; color:var(--md-on-surface-variant);">xlsx + 通报图片</div>
                        </div>
                    </div>
                    <div style="margin-top:16px;">
                        <button class="btn btn-filled btn-large" onclick="enterWorkspace('daily-report')">
                            进入非油日报入口 ${ICONS.arrow_forward}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;
}

function getRouteById(id) {
    const map = {'daily_report': 'daily-report', 'monthly_report': 'monthly-report',
                 'category_report': 'category-report', 'station_report': 'station-report'};
    return map[id] || id;
}
function getReportIcon(id) {
    const icons = {'daily_report': ICONS.description, 'monthly_report': ICONS.analytics,
                   'category_report': ICONS.receipt_long, 'station_report': ICONS.store};
    return icons[id] || ICONS.file;
}

// ===================================================
// 工作区（左侧行程栏 + 右侧内容）
// ===================================================
const routeMeta = {
    'daily-report': { title: '非油日报入口', steps: [
        {id: 'upload', label: '上传数据', icon: 'cloud_upload'},
        {id: 'adjust', label: '确认调整', icon: 'tune'},
        {id: 'process', label: '处理数据', icon: 'zap'},
        {id: 'output', label: '输出文件', icon: 'file'}
    ]},
    'monthly-report': { title: '月度汇总报表', pending: true, steps: [] },
    'category-report': { title: '大类分析报表', pending: true, steps: [] },
    'station-report': { title: '到站明细报表', pending: true, steps: [] }
};

let drState = { step: 'upload', sessionId: null, uploaded: {}, matched: {}, adjustments: [], processStatus: null, outputFormat: 'both', pollTimer: null };

function enterWorkspace(route) {
    const meta = routeMeta[route];
    if (!meta) return;
    if (meta.pending) { showSnackbar('该报表入口正在开发中', 'warning'); return; }
    drState = { step: 'upload', sessionId: null, uploaded: {}, matched: {}, adjustments: [], processStatus: null, outputFormat: 'both', pollTimer: null };
    renderWorkspace(route);
}

function renderWorkspace(route) {
    const meta = routeMeta[route];
    const steps = meta.steps;
    const currentIdx = steps.findIndex(s => s.id === drState.step);

    document.getElementById('app').innerHTML = `
        <div class="view workspace">
            <div class="workspace-rail">
                <div class="rail-header">
                    <button class="rail-back-btn" onclick="renderHome()" title="返回首页">${ICONS.arrow_back}</button>
                    <div class="rail-title">${meta.title}</div>
                </div>
                <div class="rail-section-label">工作流程</div>
                <div class="stepper" id="stepper">
                    ${steps.map((s, i) => `
                        <div class="stepper-item ${i === currentIdx ? 'active' : ''} ${i < currentIdx ? 'done' : ''}" onclick="goStep('${s.id}')">
                            <div class="stepper-icon">${i < currentIdx ? ICONS.check : ICONS[s.icon]}</div>
                            <div class="stepper-label">${s.label}</div>
                            ${i < steps.length - 1 ? '<div class="stepper-connector"></div>' : ''}
                        </div>
                    `).join('')}
                </div>
                <div class="rail-footer">
                    <div class="rail-status" id="railStatus">
                        <span class="rail-status-dot"></span>
                        <span id="railStatusText">待上传</span>
                    </div>
                </div>
            </div>
            <div class="workspace-main">
                <div class="workspace-topbar">
                    <div class="workspace-topbar-title" id="wsTitle">${meta.title}</div>
                    <div class="workspace-topbar-spacer"></div>
                    <div class="workspace-topbar-meta" id="wsMeta"></div>
                </div>
                <div class="workspace-content" id="wsContent"></div>
            </div>
        </div>
    `;
    updateRailStatus();
    renderStepContent();
}

function updateRailStatus() {
    const statusEl = document.getElementById('railStatus');
    const textEl = document.getElementById('railStatusText');
    if (!statusEl) return;
    const statusMap = {
        'upload': ['rail-status', '待上传'],
        'adjust': ['rail-status', '待确认调整'],
        'process': ['rail-status processing', '处理中'],
        'output': ['rail-status done', '已完成']
    };
    const [cls, txt] = statusMap[drState.step] || ['rail-status', '待操作'];
    statusEl.className = cls;
    textEl.textContent = txt;
}

function goStep(stepId) {
    const order = ['upload','adjust','process','output'];
    const curIdx = order.indexOf(drState.step);
    const targetIdx = order.indexOf(stepId);

    // 允许回到之前的步骤（点击左侧行程栏）
    if (targetIdx <= curIdx) {
        drState.step = stepId;
        renderWorkspace('daily-report');
        return;
    }

    // 前进到下一步时检查当前步骤是否完成
    if (targetIdx === curIdx + 1) {
        if (drState.step === 'upload' && Object.keys(drState.matched).length < 6) {
            showSnackbar('请先上传全部 6 个文件', 'warning');
            return;
        }
        drState.step = stepId;
        renderWorkspace('daily-report');
        return;
    }

    // 不允许跳过多步
    showSnackbar('请先完成当前步骤', 'warning');
}

function renderStepContent() {
    const content = document.getElementById('wsContent');
    switch(drState.step) {
        case 'upload': renderUpload(content); break;
        case 'adjust': renderAdjust(content); break;
        case 'process': renderProcess(content); break;
        case 'output': renderOutput(content); break;
    }
}

// ===================================================
// 步骤 1：上传数据（单一上传区，自动识别）
// ===================================================
function renderUpload(container) {
    container.innerHTML = `
        <div class="card">
            <div class="card-header">
                <div class="card-icon-box">${ICONS.cloud_upload}</div>
                <div style="flex-grow:1;">
                    <div class="card-title">上传导出数据</div>
                    <div class="card-subtitle">一次选择 6 张导出表，软件自动识别文件类型</div>
                </div>
            </div>
            <div class="upload-zone" id="uploadZone" onclick="selectFiles()">
                <div class="upload-zone-icon">${ICONS.cloud_upload}</div>
                <div class="upload-zone-title">点击选择文件或拖拽到此处</div>
                <div class="upload-zone-desc">支持同时选择 6 个 Excel 文件（.xlsx / .xls）</div>
                <div class="upload-zone-hint">软件会根据文件名自动识别：当期全 / 同期全 / 当期零 / CRM / 电子券 / 养车卡</div>
            </div>
            <div class="upload-result" id="uploadResult"></div>
            <div style="margin-top:24px; display:flex; gap:12px; justify-content:flex-end;">
                <button class="btn btn-text" onclick="showUploadHelp()">${ICONS.info} 帮助说明</button>
                <button class="btn btn-filled btn-large" id="btnUploadNext" onclick="goStep('adjust')" ${Object.keys(drState.matched).length < 6 ? 'disabled' : ''}>
                    下一步: 确认调整 ${ICONS.arrow_forward}
                </button>
            </div>
        </div>
    `;
    setupDragDrop();
    if (Object.keys(drState.matched).length > 0) renderUploadResult();
}

function setupDragDrop() {
    const zone = document.getElementById('uploadZone');
    if (!zone) return;
    ['dragenter','dragover'].forEach(ev => zone.addEventListener(ev, e => {
        e.preventDefault(); e.stopPropagation();
        zone.classList.add('dragover');
    }));
    ['dragleave','drop'].forEach(ev => zone.addEventListener(ev, e => {
        e.preventDefault(); e.stopPropagation();
        zone.classList.remove('dragover');
    }));
    zone.addEventListener('drop', e => {
        const files = Array.from(e.dataTransfer.files);
        if (files.length) handleFiles(files);
    });
}

function selectFiles() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.xlsx,.xls';
    input.multiple = true;
    input.onchange = e => {
        const files = Array.from(e.target.files);
        if (files.length) handleFiles(files);
    };
    input.click();
}

async function handleFiles(files) {
    showSnackbar(`正在上传 ${files.length} 个文件...`);
    const formData = new FormData();
    files.forEach(f => formData.append('files', f));
    try {
        const result = await apiUpload('/api/daily-report/upload-multi', formData);
        if (result.status === 'success' || result.status === 'partial') {
            drState.sessionId = result.session_id;
            drState.matched = result.matched || {};
            drState.uploaded = result.uploaded || {};
            const matchedCount = Object.keys(drState.matched).length;
            showSnackbar(`识别成功 ${matchedCount}/6 个文件`, matchedCount === 6 ? 'success' : 'warning');
            renderUploadResult();
            const btn = document.getElementById('btnUploadNext');
            if (btn) btn.disabled = matchedCount < 6;
        } else {
            showSnackbar('上传失败: ' + (result.message || '未知错误'), 'error');
        }
    } catch (e) {
        showSnackbar('上传失败: ' + e.message, 'error');
    }
}

function renderUploadResult() {
    const container = document.getElementById('uploadResult');
    if (!container) return;
    const expected = [
        {key: 'dangqi_all', name: '当期全'},
        {key: 'tongqi_all', name: '同期全'},
        {key: 'dangqi_ling', name: '当期零'},
        {key: 'crm', name: 'CRM'},
        {key: 'dianzi_quan', name: '电子券'},
        {key: 'yangche_ka', name: '养车卡'}
    ];
    container.innerHTML = expected.map(e => {
        const matched = drState.matched[e.key];
        const fileName = drState.uploaded[e.key];
        if (matched) {
            return `<div class="upload-result-item matched">
                <div class="upload-result-icon">${ICONS.check}</div>
                <div class="upload-result-info">
                    <div class="upload-result-name">${fileName || e.name}</div>
                    <div class="upload-result-type">已识别为: ${e.name}</div>
                </div>
            </div>`;
        } else {
            return `<div class="upload-result-item unmatched">
                <div class="upload-result-icon">${ICONS.error}</div>
                <div class="upload-result-info">
                    <div class="upload-result-name">${e.name}</div>
                    <div class="upload-result-type">未上传</div>
                </div>
            </div>`;
        }
    }).join('');
}

function showUploadHelp() {
    showModal('上传说明', `
        <p style="margin-bottom:12px;">请从业务系统导出以下 6 个文件，可一次全选上传：</p>
        <div style="display:flex; flex-direction:column; gap:8px;">
            ${[ ['当期全.xlsx','当期全部大类销售明细'],['同期全.xlsx','同期全部大类销售明细'],
                ['当期零.xlsx','当期零售明细'],['CRM.xlsx','CRM用券明细'],
                ['电子券.xlsx','电子券核销明细'],['养车卡.xlsx','养车卡销售明细'] ].map(([n,d]) => `
                <div style="display:flex; align-items:center; gap:12px; padding:12px; background:var(--md-surface-container); border-radius:var(--shape-sm);">
                    <div style="width:36px; height:36px; border-radius:var(--shape-xs); background:var(--md-primary-container); color:var(--md-on-primary-container); display:flex; align-items:center; justify-content:center;">${ICONS.file}</div>
                    <div><div style="font-weight:500;">${n}</div><div style="font-size:12px; color:var(--md-on-surface-variant);">${d}</div></div>
                </div>
            `).join('')}
        </div>
        <p style="margin-top:16px; color:var(--md-on-surface-variant); font-size:13px;">软件根据文件名自动识别类型，文件名包含上述关键词即可。</p>
    `);
}

// ===================================================
// 步骤 2：确认调整
// ===================================================
function renderAdjust(container) {
    container.innerHTML = `
        <div class="card">
            <div class="card-header">
                <div class="card-icon-box">${ICONS.tune}</div>
                <div style="flex-grow:1;">
                    <div class="card-title">是否需要进行调整？</div>
                    <div class="card-subtitle">如有跨站销售、人工调增/调减等情况，请添加调整数据</div>
                </div>
            </div>
            <div id="adjustList" style="margin-bottom:16px;">
                ${drState.adjustments.length === 0
                    ? '<p style="color:var(--md-on-surface-variant); padding:24px; text-align:center; background:var(--md-surface-container-low); border-radius:var(--shape-md);">暂无调整数据，可直接开始处理</p>'
                    : drState.adjustments.map((adj, i) => `
                        <div class="card" style="margin-bottom:8px; padding:16px;">
                            <div style="display:flex; align-items:center; gap:12px;">
                                <div style="flex-grow:1;">
                                    <div style="font-weight:500;">${adj.station}</div>
                                    <div style="font-size:12px; color:var(--md-on-surface-variant);">${getAdjustTypeLabel(adj.type)}: ${adj.value} 元 ${adj.reason ? '· ' + adj.reason : ''}</div>
                                </div>
                                <button class="btn btn-text btn-icon" onclick="removeAdjustment(${i})" title="删除">${ICONS.delete}</button>
                            </div>
                        </div>
                    `).join('')
                }
            </div>
            <button class="btn btn-tonal" onclick="showAddAdjustDialog()">${ICONS.add} 添加调整</button>
            <div style="margin-top:24px; padding-top:24px; border-top:1px solid var(--md-outline-variant); display:flex; gap:12px; justify-content:space-between; align-items:center;">
                <button class="btn btn-text" onclick="goStep('upload')">${ICONS.arrow_back} 返回上传</button>
                <div style="display:flex; gap:12px; align-items:center;">
                    <div class="text-field" style="min-width:200px;">
                        <label>输出格式</label>
                        <select id="outputFormatSelect">
                            <option value="both" ${drState.outputFormat==='both'?'selected':''}>xlsx + 通报图片</option>
                            <option value="xlsx" ${drState.outputFormat==='xlsx'?'selected':''}>仅 xlsx</option>
                            <option value="image" ${drState.outputFormat==='image'?'selected':''}>仅通报图片</option>
                        </select>
                    </div>
                    <button class="btn btn-filled btn-large" onclick="startProcess()">${ICONS.play} 开始处理</button>
                </div>
            </div>
        </div>
    `;
    const sel = document.getElementById('outputFormatSelect');
    if (sel) sel.onchange = e => drState.outputFormat = e.target.value;
}

function getAdjustTypeLabel(type) {
    return {'sales_add':'销售调增','sales_sub':'销售调减','profit_add':'毛利调增','profit_sub':'毛利调减'}[type] || type;
}

function showAddAdjustDialog() {
    const stations = ['淇县','浚县','市区经营部','商客','鹤壁市新源站便利店','鹤壁市淇县二站便利店','鹤壁市浚县金城站便利店'];
    showModal('添加调整数据', `
        <div style="display:flex; flex-direction:column; gap:16px;">
            <div class="text-field"><label>站点名称</label><input type="text" id="adjStation" list="stationList" placeholder="输入或选择站点"><datalist id="stationList">${stations.map(s=>`<option value="${s}">`).join('')}</datalist></div>
            <div class="text-field"><label>调整类型</label><select id="adjType"><option value="sales_add">销售调增</option><option value="sales_sub">销售调减</option><option value="profit_add">毛利调增</option><option value="profit_sub">毛利调减</option></select></div>
            <div class="text-field"><label>调整金额（元）</label><input type="number" id="adjValue" placeholder="0.00" step="0.01"></div>
            <div class="text-field"><label>调整原因（选填）</label><input type="text" id="adjReason" placeholder="如：跨站销售调整"></div>
        </div>
    `, [
        {label:'取消', cls:'btn-text', action:'closeModal'},
        {label:'添加', cls:'btn-filled', action:'confirmAddAdjust'}
    ]);
}

function confirmAddAdjust() {
    const station = document.getElementById('adjStation').value.trim();
    const type = document.getElementById('adjType').value;
    const value = parseFloat(document.getElementById('adjValue').value);
    const reason = document.getElementById('adjReason').value.trim();
    if (!station) { showSnackbar('请输入站点名称', 'warning'); return; }
    if (isNaN(value) || value === 0) { showSnackbar('请输入有效金额', 'warning'); return; }
    drState.adjustments.push({station, type, value, reason});
    closeModal();
    showSnackbar('调整已添加', 'success');
    renderStepContent();
}

function removeAdjustment(index) {
    drState.adjustments.splice(index, 1);
    renderStepContent();
}

// ===================================================
// 步骤 3：处理数据
// ===================================================
async function startProcess() {
    showConfirm('确认开始处理', `即将处理非油日报数据，共 ${Object.keys(drState.matched).length} 个数据文件，${drState.adjustments.length} 条调整记录。是否继续？`, async () => {
        drState.step = 'process';
        renderWorkspace('daily-report');
        try {
            const result = await apiPost('/api/daily-report/process', {
                session_id: drState.sessionId,
                adjustments: drState.adjustments,
                output_format: drState.outputFormat
            });
            if (result.status === 'started') {
                showSnackbar('处理已启动', 'success');
                pollProcessStatus();
            } else {
                showSnackbar('启动失败: ' + result.message, 'error');
                drState.step = 'adjust';
                renderWorkspace('daily-report');
            }
        } catch (e) {
            showSnackbar('处理失败: ' + e.message, 'error');
            drState.step = 'adjust';
            renderWorkspace('daily-report');
        }
    });
}

function pollProcessStatus() {
    if (drState.pollTimer) clearInterval(drState.pollTimer);
    drState.pollTimer = setInterval(async () => {
        try {
            const status = await api('/api/daily-report/status');
            drState.processStatus = status;
            updateProgressUI(status);
            if (status.status === 'done' || status.status === 'error') {
                clearInterval(drState.pollTimer);
                drState.pollTimer = null;
                if (status.status === 'done') {
                    drState.step = 'output';
                    showSnackbar('处理完成！', 'success');
                    setTimeout(() => renderWorkspace('daily-report'), 800);
                } else {
                    showSnackbar('处理出错: ' + status.message, 'error');
                }
            }
        } catch (e) { console.error('poll error', e); }
    }, 1000);
}

function renderProcess(container) {
    const status = drState.processStatus || {status:'processing', progress:0, message:'准备中...', step:0};
    container.innerHTML = `
        <div class="card">
            <div class="card-header">
                <div class="card-icon-box">${ICONS.zap}</div>
                <div style="flex-grow:1;">
                    <div class="card-title">正在处理数据</div>
                    <div class="card-subtitle" id="progressMessage">${status.message || '准备中...'}</div>
                </div>
                <div id="progressPercent" style="font-size:20px; font-weight:600; color:var(--md-primary);">${(status.progress||0)}%</div>
            </div>
            <div class="progress-track" style="margin-bottom:20px;">
                <div class="progress-fill" id="progressBar" style="width:${status.progress||0}%"></div>
            </div>
            <div class="step-list" id="stepList"></div>
        </div>
    `;
    updateProgressUI(status);
}

function updateProgressUI(status) {
    const bar = document.getElementById('progressBar');
    const msg = document.getElementById('progressMessage');
    const pct = document.getElementById('progressPercent');
    if (bar) bar.style.width = (status.progress || 0) + '%';
    if (pct) pct.textContent = (status.progress || 0) + '%';
    if (msg) msg.textContent = status.message || '';
    const stepList = document.getElementById('stepList');
    if (stepList) {
        const steps = [
            {n:1, text:'加载导出数据文件'},{n:2, text:'大类原始数据入库'},
            {n:3, text:'剔除烟草的零售销售'},{n:4, text:'洗车券处理'},
            {n:5, text:'销售额与毛利汇总'},{n:6, text:'CRM券处理'},
            {n:7, text:'新零售电子券处理'},{n:8, text:'养车卡调整'},
            {n:9, text:'构建附表'},{n:10, text:'刷新透视表与通报数据'}
        ];
        const cur = status.step || 0;
        stepList.innerHTML = steps.map(s => {
            let cls = s.n < cur ? 'done' : s.n === cur ? (status.status === 'error' ? 'error' : 'current') : '';
            const icon = s.n < cur ? ICONS.check : s.n;
            return `<div class="step-row ${cls}"><div class="step-row-num">${icon}</div><div class="step-row-text">${s.text}</div><div class="step-row-status">${s.n < cur ? '已完成' : s.n === cur ? '处理中...' : '等待中'}</div></div>`;
        }).join('');
    }
}

// ===================================================
// 步骤 4：输出文件
// ===================================================
function renderOutput(container) {
    container.innerHTML = `
        <div class="card" style="text-align:center; padding:40px;">
            <div style="width:80px; height:80px; margin:0 auto 16px; border-radius:var(--shape-full); background:var(--md-success-container); color:var(--md-success); display:flex; align-items:center; justify-content:center;">${ICONS.check_circle}</div>
            <h3 style="font-size:20px; font-weight:600; margin-bottom:8px;">处理完成</h3>
            <p style="color:var(--md-on-surface-variant); margin-bottom:24px;">报表已生成，可查看预览与下载文件</p>
            <div style="display:flex; gap:12px; justify-content:center; flex-wrap:wrap;">
                <button class="btn btn-tonal" onclick="loadPreview()">${ICONS.visibility} 查看预览</button>
                <button class="btn btn-tonal" onclick="loadOutputs()">${ICONS.folder} 查看文件</button>
                <button class="btn btn-filled" onclick="enterWorkspace('daily-report')">${ICONS.refresh} 制作新报表</button>
            </div>
        </div>
        <div class="card" id="previewCard" style="display:none;">
            <div class="card-header">
                <div class="card-icon-box">${ICONS.table_chart}</div>
                <div style="flex-grow:1;"><div class="card-title">输出预览</div></div>
            </div>
            <div id="previewContent"></div>
        </div>
        <div class="card">
            <div class="card-header">
                <div class="card-icon-box">${ICONS.folder}</div>
                <div style="flex-grow:1;"><div class="card-title">输出文件</div></div>
                <button class="btn btn-text" onclick="loadOutputs()">${ICONS.refresh}</button>
            </div>
            <div class="file-list" id="outputList"></div>
        </div>
    `;
    loadOutputs();
}

async function loadPreview() {
    document.getElementById('previewCard').style.display = '';
    try {
        const result = await api('/api/daily-report/preview');
        const content = document.getElementById('previewContent');
        if (result.status === 'success') {
            const tongbao = result.tongbao || [];
            let html = '<div style="overflow:auto;"><table class="data-table"><thead><tr>';
            if (tongbao[0]) tongbao[0].forEach(h => html += `<th>${h || ''}</th>`);
            html += '</tr></thead><tbody>';
            tongbao.slice(1).forEach(row => { html += '<tr>'; row.forEach(c => html += `<td>${c !== null ? c : ''}</td>`); html += '</tr>'; });
            html += '</tbody></table></div>';
            content.innerHTML = html;
        } else {
            content.innerHTML = `<p style="color:var(--md-on-surface-variant);">${result.message}</p>`;
        }
    } catch (e) {
        document.getElementById('previewContent').innerHTML = `<p style="color:var(--md-error);">加载预览失败: ${e.message}</p>`;
    }
}

async function loadOutputs() {
    try {
        const result = await api('/api/outputs/list');
        const content = document.getElementById('outputList');
        if (!content) return;
        const files = (result.files || []).filter(f => f.name !== '.gitkeep');
        if (files.length === 0) {
            content.innerHTML = '<p style="color:var(--md-on-surface-variant); padding:16px; text-align:center;">暂无输出文件</p>';
            return;
        }
        content.innerHTML = files.map(f => `
            <div class="file-list-item">
                <div class="file-list-icon">${f.name.endsWith('.png') ? ICONS.image : ICONS.file}</div>
                <div class="file-list-info">
                    <div class="file-list-name">${f.name}</div>
                    <div class="file-list-meta">${(f.size/1024).toFixed(1)} KB · ${new Date(f.time).toLocaleString()}</div>
                </div>
                <a class="btn btn-tonal" href="/api/download/${encodeURIComponent(f.name)}" download>${ICONS.download} 下载</a>
            </div>
        `).join('');
    } catch (e) {
        const content = document.getElementById('outputList');
        if (content) content.innerHTML = `<p>加载失败: ${e.message}</p>`;
    }
}

// ===================================================
// Snackbar / Modal
// ===================================================
function showSnackbar(message, type = 'info') {
    const container = document.getElementById('snackbarContainer');
    const snack = document.createElement('div');
    snack.className = `snackbar ${type}`;
    snack.innerHTML = `${type === 'success' ? ICONS.check : type === 'error' ? ICONS.error : type === 'warning' ? ICONS.info : ''}<span>${message}</span>`;
    container.appendChild(snack);
    setTimeout(() => {
        snack.style.opacity = '0';
        snack.style.transform = 'translateY(20px)';
        snack.style.transition = 'all var(--duration-short3)';
        setTimeout(() => snack.remove(), 250);
    }, 3000);
}

function showModal(title, content, actions = null) {
    const container = document.getElementById('modalContainer');
    let actionsHtml = actions
        ? `<div class="modal-actions">${actions.map(a => `<button class="btn ${a.cls}" onclick="${a.action}">${a.label}</button>`).join('')}</div>`
        : `<div class="modal-actions"><button class="btn btn-text" onclick="closeModal()">关闭</button></div>`;
    container.innerHTML = `<div class="modal-overlay" onclick="if(event.target===this) closeModal()"><div class="modal"><div class="modal-title">${title}</div><div>${content}</div>${actionsHtml}</div></div>`;
}

function closeModal() { document.getElementById('modalContainer').innerHTML = ''; }

function showConfirm(title, message, onConfirm) {
    document.getElementById('modalContainer').innerHTML = `
        <div class="modal-overlay" onclick="if(event.target===this) closeModal()">
            <div class="modal" style="min-width:420px;">
                <div class="modal-title">${title}</div>
                <p style="color:var(--md-on-surface-variant); margin-bottom:24px;">${message}</p>
                <div class="modal-actions">
                    <button class="btn btn-text" onclick="closeModal()">取消</button>
                    <button class="btn btn-filled" id="confirmBtn">确认</button>
                </div>
            </div>
        </div>`;
    document.getElementById('confirmBtn').onclick = () => { closeModal(); onConfirm(); };
}

// ===== 启动 =====
window.addEventListener('DOMContentLoaded', init);
