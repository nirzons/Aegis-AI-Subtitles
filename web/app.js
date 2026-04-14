const elements = {
    connectionStatus: document.getElementById('connection-status'),
    statusText: document.querySelector('.status-text'),
    progressText: document.getElementById('progress-text'),
    progressPercent: document.getElementById('progress-percent'),
    progressFill: document.getElementById('progress-fill'),
    timerLabel: document.getElementById('timer-label'),
    etaLabel: document.getElementById('eta-label'),
    costDisplay: document.getElementById('cost-display'),
    currentStatus: document.getElementById('current-status'),
    finishTime: document.getElementById('finish-time'),
    terminal: document.getElementById('terminal'),
    autoscrollBtn: document.getElementById('autoscroll-btn'),
    clearBtn: document.getElementById('clear-btn'),
    translationFeed: document.getElementById('translation-feed'),
    feedToggleBtn: document.getElementById('feed-toggle-btn'),
    liveViewerSection: document.querySelector('.live-viewer-section')
};

let socket = null;
let isAutoscroll = true;
let lastVersion = -1;

function connect() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;
    
    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        console.log('Connected to Aegis WebSocket');
        elements.connectionStatus.classList.remove('badge-error');
        elements.connectionStatus.classList.add('badge-success');
        elements.statusText.textContent = 'Connected';
    };

    socket.onmessage = (event) => {
        const state = JSON.parse(event.data);
        updateUI(state);
    };

    socket.onclose = () => {
        console.log('Disconnected from Aegis WebSocket');
        elements.connectionStatus.classList.remove('badge-success');
        elements.connectionStatus.classList.add('badge-error');
        elements.statusText.textContent = 'Disconnected';
        
        // Auto-reconnect after 2 seconds
        setTimeout(connect, 2000);
    };

    socket.onerror = (error) => {
        console.error('WebSocket Error:', error);
        socket.close();
    };
}

function updateUI(state) {
    // 1. Progress
    const p = state.progress;
    elements.progressText.textContent = `${p.processed}/${p.total}`;
    elements.progressPercent.textContent = `${p.percent}%`;
    elements.progressFill.style.width = `${p.percent}%`;

    // 2. Timer & ETA
    elements.timerLabel.textContent = state.timer.label || '--:--';
    elements.etaLabel.textContent = `ETA: ${state.eta.time_remaining || '--:--'}`;

    // 3. Cost
    elements.costDisplay.textContent = state.cost.display || '$0.00';
    
    // 4. Status
    elements.currentStatus.textContent = state.status.text || 'Idle';
    elements.currentStatus.style.color = state.status.color;
    elements.finishTime.textContent = `Ends: ${state.eta.finish_time || '--:--'}`;

    // 5. Logs & Segments
    if (state.version !== lastVersion) {
        renderLogs(state.log_lines);
        renderSegments(state.segments, state.upcoming);
        lastVersion = state.version;
    }
}

function renderSegments(segments, upcoming) {
    const feed = elements.translationFeed;
    if (!feed) return;

    let html = '';

    // Completed segments (last 50)
    segments.forEach(seg => {
        html += `
            <div class="translation-row">
                <div class="col-idx">${seg.index}</div>
                <div class="col-eng">${escapeHtml(seg.eng)}</div>
                <div class="col-heb">${seg.heb}</div>
            </div>
        `;
    });

    // Upcoming (next 2)
    upcoming.forEach(up => {
        html += `
            <div class="translation-row upcoming">
                <div class="col-idx">${up.index}</div>
                <div class="col-eng">${escapeHtml(up.text)}</div>
                <div class="col-heb">Next up...</div>
            </div>
        `;
    });

    const currentScroll = feed.scrollTop;
    const isAtBottom = feed.scrollHeight - feed.scrollTop <= feed.clientHeight + 50;
    
    feed.innerHTML = html;

    // Follow the bottom if was already at bottom (to see new translations)
    if (isAtBottom) {
        feed.scrollTop = feed.scrollHeight;
    } else {
        feed.scrollTop = currentScroll;
    }
}

function renderLogs(lines) {
    const term = elements.terminal;
    
    // Simple approach: Replace content to ensure alignment with the 500-line buffer
    // For local use, this is fast enough.
    term.innerHTML = lines.map(line => `<div class="log-line">${escapeHtml(line)}</div>`).join('');
    
    if (isAutoscroll) {
        term.scrollTop = term.scrollHeight;
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// User Interaction
elements.autoscrollBtn.addEventListener('click', () => {
    isAutoscroll = !isAutoscroll;
    elements.autoscrollBtn.classList.toggle('active', isAutoscroll);
    elements.autoscrollBtn.textContent = `Auto-scroll: ${isAutoscroll ? 'ON' : 'OFF'}`;
});

elements.clearBtn.addEventListener('click', () => {
    elements.terminal.innerHTML = '';
});

// Detect manual scroll to pause autoscroll
elements.terminal.addEventListener('scroll', () => {
    const term = elements.terminal;
    const isAtBottom = term.scrollHeight - term.scrollTop <= term.clientHeight + 10;
    
    if (!isAtBottom && isAutoscroll) {
        // Optional: comment this out if you want strict button control
        // isAutoscroll = false;
        // elements.autoscrollBtn.classList.remove('active');
        // elements.autoscrollBtn.textContent = 'Auto-scroll: OFF';
    }
});

// Feed Toggle
if (elements.feedToggleBtn) {
    const toggleText = elements.feedToggleBtn.querySelector('.toggle-text');
    const isCollapsed = localStorage.getItem('aegis-feed-collapsed') === 'true';
    if (isCollapsed) {
        elements.liveViewerSection.classList.add('collapsed');
        if (toggleText) toggleText.textContent = 'Expand';
    }

    elements.feedToggleBtn.addEventListener('click', () => {
        const collapsed = elements.liveViewerSection.classList.toggle('collapsed');
        if (toggleText) toggleText.textContent = collapsed ? 'Expand' : 'Minimize';
        localStorage.setItem('aegis-feed-collapsed', collapsed);
    });
}

// Initialize
connect();
