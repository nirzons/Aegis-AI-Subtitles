const elements = {
    progressText: document.getElementById('progress-text'),
    progressPercent: document.getElementById('progress-percent'), // ADD THIS
    progressFill: document.getElementById('progress-fill'),       // ADD THIS
    etaLabel: document.getElementById('eta-label'),
    tokensSecText: document.getElementById('tokens-sec-text'),
    sparklineChart: document.getElementById('sparkline-chart'),
    cacheBadge: document.getElementById('cache-badge'),
    costTotal: document.getElementById('cost-total'),
    costMain: document.getElementById('cost-main'),
    costJudge: document.getElementById('cost-judge'),
    lastDecision: document.getElementById('last-decision'),
    statusDot: document.getElementById('status-dot'),
    statusText: document.getElementById('status-text'),
    batchSize: document.getElementById('batch-size'),
    batchTrendIcon: document.getElementById('batch-trend-icon'),
    timerText: document.getElementById('timer-text'),
    timerDivider: document.getElementById('timer-divider'),
    syncDot: document.getElementById('sync-dot'),
    syncText: document.getElementById('sync-text'),
    
    logFilter: document.getElementById('log-filter'),
    terminalBody: document.getElementById('terminal-body'),
    translationFeed: document.getElementById('translation-feed-content')
};

let socket = null;
let lastVersion = -1;
let storedLogs = [];
let prevBatchSize = 0;

function connect() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;
    
    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        elements.syncDot.classList.replace('bg-red-500', 'bg-emerald-500');
        elements.syncDot.classList.replace('shadow-[0_0_6px_#ef4444]', 'shadow-[0_0_6px_#10b981]');
        elements.syncText.classList.replace('text-red-500', 'text-emerald-500');
        elements.syncText.textContent = 'SYNC';
    };

    socket.onmessage = (event) => {
        elements.syncDot.style.opacity = '0.5';
        setTimeout(() => elements.syncDot.style.opacity = '1', 150);

        const state = JSON.parse(event.data);
        updateUI(state);
    };

    socket.onerror = () => socket.close();

    socket.onclose = () => {
        elements.syncDot.classList.replace('bg-emerald-500', 'bg-red-500');
        elements.syncDot.classList.replace('shadow-[0_0_6px_#10b981]', 'shadow-[0_0_6px_#ef4444]');
        elements.syncText.classList.replace('text-emerald-500', 'text-red-500');
        elements.syncText.textContent = 'OFFLINE';
        setTimeout(connect, 2000);
    };
}

function updateUI(state) {
    // 1. Progress & ETA
    const p = state.progress;
    elements.progressText.innerHTML = `${p.processed}<span class="text-neutral-500 text-sm">/${p.total}</span>`;
    elements.etaLabel.textContent = state.eta.time_remaining || '--:--';
    
    // ADD THESE TWO LINES:
    if (elements.progressPercent) elements.progressPercent.textContent = `${p.percent}%`;
    if (elements.progressFill) elements.progressFill.style.width = `${p.percent}%`;    
    
    if (state.telemetry) {
        const formatCost = (val, dec) => {
            if (val > 100) return Math.floor(val).toLocaleString();
            return '$' + val.toFixed(dec);
        };

        const total = state.telemetry.cost_main + state.telemetry.cost_judge;
        const spd = state.telemetry.tokens_per_sec ?? 0;
        elements.tokensSecText.textContent = spd < 10 ? spd.toFixed(2) : spd.toFixed(1);
        elements.sparklineChart.textContent = generateSparkline(state.telemetry.speed_history);
        elements.cacheBadge.innerHTML = `<i class="fas fa-bolt text-[8px]"></i> Cache ${state.telemetry.cache_hit_percent}%`;
        
        elements.costTotal.textContent = formatCost(total, 4);
        elements.costMain.textContent  = `M: ${formatCost(state.telemetry.cost_main, 3)}`;
        elements.costJudge.textContent = `J: ${formatCost(state.telemetry.cost_judge, 3)}`;
    }

    if (state.audit) {
        elements.lastDecision.textContent = state.audit.last_decision || 'Active';

        const sz = state.audit.batch_size;
        elements.batchSize.textContent = sz;

        // Only update the arrow when batch size actually changes.
        // Ignoring same-size messages (e.g. from update_status) keeps the arrow
        // visible until the next genuine size change — mirrors Tkinter's lbl_status.
        if (sz > 0 && sz !== prevBatchSize) {
            elements.batchTrendIcon.className = 'fas text-[10px] ';
            if (prevBatchSize > 0 && sz > prevBatchSize)      elements.batchTrendIcon.className += 'fa-arrow-up text-emerald-400';
            else if (prevBatchSize > 0 && sz < prevBatchSize) elements.batchTrendIcon.className += 'fa-arrow-down text-amber-400';
            else                                               elements.batchTrendIcon.className += 'fa-minus text-neutral-500';
            prevBatchSize = sz;
        }
    }

    const timerLabel = state.timer.label || '';
    elements.timerText.innerHTML = timerLabel;
    
    // Hide timer and divider if label is empty (e.g. during Judging or Idle)
    const isVisible = !!timerLabel;
    elements.timerText.classList.toggle('hidden', !isVisible);
    if (elements.timerDivider) elements.timerDivider.classList.toggle('hidden', !isVisible);

    elements.statusText.textContent = state.status.text || 'Idle';
    elements.statusText.style.color = state.status.color;
    elements.statusDot.style.backgroundColor = state.status.color;
    elements.statusDot.style.boxShadow = `0 0 8px ${state.status.color}`;

    if (state.version !== lastVersion) {
        storedLogs = state.log_lines;
        renderLogs();
        renderSegments(state.segments, state.upcoming);
        lastVersion = state.version;
    }
}

function generateSparkline(history) {
    if (!history || history.length === 0) return '';
    const ticks = [' ', '▂', '▃', '▄', '▅', '▆', '▇', '█'];
    const min = Math.min(...history);
    const max = Math.max(...history);
    const range = max - min || 1;
    return history.map(val => {
        const index = Math.floor(((val - min) / range) * (ticks.length - 1));
        return ticks[index];
    }).join('');
}

elements.logFilter.addEventListener('input', renderLogs);

function renderLogs() {
    const term = elements.terminalBody;
    const filterText = elements.logFilter.value.toLowerCase();
    
    const filteredLines = filterText 
        ? storedLogs.filter(line => line.toLowerCase().includes(filterText)) 
        : storedLogs;

    // Advanced Terminal Syntax Highlighting matching your screenshot
    const isAtBottom = term.scrollHeight - term.scrollTop <= term.clientHeight + 80;
    term.innerHTML = filteredLines.map(line => {
        let escaped = escapeHtml(line);
        
        // Match specific tags and emojis from your backend
        if (escaped.includes('✅')) {
            escaped = `<span class="text-emerald-400">${escaped}</span>`;
        } else if (escaped.includes('⚠️') || escaped.includes('Batch Failure')) {
            escaped = `<span class="text-rose-400 font-bold">${escaped}</span>`;
        } else if (escaped.includes('🔍') || escaped.includes('Auditor Flag')) {
            escaped = `<span class="text-amber-400">${escaped}</span>`;
        } else if (escaped.includes('🧹') || escaped.includes('Sanitizer')) {
            escaped = `<span class="text-orange-400">${escaped}</span>`;
        } else if (escaped.includes('💰') || escaped.includes('[Main Model]')) {
            escaped = `<span class="text-sky-400">${escaped}</span>`;
        } else if (escaped.includes('🔄')) {
            escaped = `<span class="text-blue-400">${escaped}</span>`;
        } else if (escaped.includes('🚀')) {
            escaped = `<span class="text-emerald-300 font-semibold">${escaped}</span>`;
        } else if (escaped.includes('SESSION RESUMED')) {
            escaped = `<span class="text-neutral-500 font-bold tracking-widest">${escaped}</span>`;
        } else if (escaped.includes('⌛') || escaped.includes('Sending Batch')) {
            escaped = `<span class="text-neutral-500">${escaped}</span>`;
        } else {
            // Default coloring for unmatched text
            escaped = `<span class="text-neutral-300">${escaped}</span>`;
        }

        return `<div>${escaped}</div>`;
    }).join('');
    
    if (isAtBottom) term.scrollTop = term.scrollHeight;
}

function renderSegments(segments, upcoming) {
    const feed = elements.translationFeed;
    if (!feed) return;

    // subs-body is the actual scroll container (overflow-y-auto), not the inner content div
    const scrollContainer = document.getElementById('subs-body');

    let html = '';
    
    segments.forEach(seg => {
        html += `
        <div class="grid grid-cols-12 gap-4 items-center py-2 border-b border-neutral-800/50 hover:bg-neutral-900/50 transition-colors">
            <div class="col-span-1 text-center text-xs mono text-neutral-600">${seg.index}</div>
            <div class="col-span-5 text-sm text-neutral-300 not-italic">${renderSrtTags(seg.eng)}</div>
            <div class="col-span-6 text-right text-[15px] font-semibold text-emerald-400" dir="rtl">${renderSrtTags(seg.heb)}</div>
        </div>`;
    });


    upcoming.forEach(up => {
        html += `
        <div class="grid grid-cols-12 gap-4 items-center py-2 border-b border-neutral-800/50 opacity-50 border-dashed">
            <div class="col-span-1 text-center text-xs mono text-neutral-600">${up.index}</div>
            <div class="col-span-5 text-sm text-neutral-300 not-italic">${renderSrtTags(up.text)}</div>
            <div class="col-span-6 text-right text-sm font-semibold text-neutral-500">Next up...</div>
        </div>`;
    });




    const isAtBottom = scrollContainer
        ? scrollContainer.scrollHeight - scrollContainer.scrollTop <= scrollContainer.clientHeight + 50
        : true;
    feed.innerHTML = html;
    if (isAtBottom && scrollContainer) scrollContainer.scrollTop = scrollContainer.scrollHeight;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Renders SRT formatting tags (i, b, u, font) as safe HTML.
 * Escapes everything first, then restores the specific allowed tags.
 */
function renderSrtTags(text) {
    if (!text) return '';
    // Escape standard HTML to prevent XSS
    let escaped = escapeHtml(text);
    
    // Restore basic tags: <i>, <b>, <u> and their closing tags
    // The regex handles potential spaces like < i > or </ i> which sometimes occur in local LLM outputs
    escaped = escaped.replace(/&lt;\s*(\/?[ibu])\s*&gt;/gi, '<$1>');
    
    // Restore font color tags: handles <font color="#RRGGBB"> and <font color=#RRGGBB>
    // Pattern matches the escaped version of the tags
    escaped = escaped.replace(/&lt;\s*font\s+color\s*=\s*(&quot;)?(#[a-fA-F0-9]{3,8}|[a-zA-Z0-9]+)(&quot;)?\s*&gt;/gi, (match, q1, color, q2) => {
        return `<span style="color: ${color}">`;
    });
    
    // Close font tag
    escaped = escaped.replace(/&lt;\s*\/font\s*&gt;/gi, '</span>');
    
    return escaped;
}



connect();