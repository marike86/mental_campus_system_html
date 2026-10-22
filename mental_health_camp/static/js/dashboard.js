function renderCalendarHeatmap(container, calendar) {
    if (!container || !calendar || calendar.length === 0) return;
    var html = '<div class="grid grid-cols-7 gap-1.5">';
    var dayNames = ['一', '二', '三', '四', '五', '六', '日'];
    for (var d = 0; d < 7; d++) {
        html += '<div class="text-center text-xs text-gray-400 font-medium py-1">' + dayNames[d] + '</div>';
    }
    var firstDate = new Date(calendar[0].date);
    var startDow = (firstDate.getDay() + 6) % 7;
    for (var s = 0; s < startDow; s++) {
        html += '<div></div>';
    }
    for (var i = 0; i < calendar.length; i++) {
        var day = calendar[i];
        var bgClass, textColor;
        if (day.status === 'approved') {
            bgClass = 'bg-brand-800';
            textColor = 'text-white';
        } else if (['available','rejected'].includes(day.status)) {
            bgClass = 'bg-red-100';
            textColor = 'text-red-400';
        } else {
            bgClass = 'bg-gray-100';
            textColor = 'text-gray-400';
        }
        html += '<div class="aspect-square rounded-lg flex items-center justify-center text-xs font-medium ' + bgClass + ' ' + textColor + ' cursor-default" title="第' + day.day + '天 - ' + ({approved:'已完成',pending:'待审核',available:'可学习',rejected:'需修改',locked:'已锁定',future:'未开始'}[day.status] || '') + '">' + day.day + '</div>';
    }
    html += '</div>';
    html += '<div class="flex items-center space-x-4 mt-3">';
    html += '<div class="flex items-center space-x-1"><div class="w-3 h-3 rounded bg-brand-800"></div><span class="text-xs text-gray-500">已完成</span></div>';
    html += '<div class="flex items-center space-x-1"><div class="w-3 h-3 rounded bg-red-100"></div><span class="text-xs text-gray-500">未完成</span></div>';
    html += '<div class="flex items-center space-x-1"><div class="w-3 h-3 rounded bg-gray-100"></div><span class="text-xs text-gray-500">未到来</span></div>';
    html += '</div>';
    container.innerHTML = html;
}

function renderStreakCounter(container, streak) {
    if (!container) return;
    var flames = '';
    for (var i = 0; i < Math.min(streak, 30); i++) {
        flames += '🔥';
    }
    container.innerHTML = '<div class="text-center"><div class="text-4xl mb-2">' + (streak > 0 ? flames : '💤') + '</div><div class="text-3xl font-bold text-gray-900">' + streak + '</div><div class="text-sm text-gray-500">连续打卡天数</div></div>';
}

function initLikertChart(canvasId, seriesData) {
    const entries = Object.entries(seriesData || {});
    const canvas = document.getElementById(canvasId);
    if (!entries.length || !canvas || typeof Chart === 'undefined') return;
    const days = [...new Set(entries.flatMap(([, series]) => series.data.map(point => point.day)))].sort((a,b) => a-b);
    const colors = ['#9c0c13', '#0891b2', '#7c3aed', '#b45309'];
    const datasets = entries.map(([key, series], index) => ({
        label: series.label + (series.version_label ? ' · ' + series.version_label : ''),
        data: days.map(day => series.data.find(point => point.day === day)?.value ?? null),
        borderColor: colors[index % colors.length],
        backgroundColor: colors[index % colors.length],
        fill: false, spanGaps: false, pointRadius: 5
    }));
    const values = datasets.flatMap(series => series.data.filter(value => value !== null));
    new Chart(canvas.getContext('2d'), {
        type: 'line', data: {labels: days.map(day => '第' + day + '天'), datasets},
        options: {
            responsive: true, maintainAspectRatio: false,
            scales: {y: {min: Math.min(0, ...values), max: Math.max(5, ...values), ticks: {stepSize: 1}}},
            plugins: {legend: {display: true}, tooltip: {callbacks: {
                afterLabel: function(context) {
                    const series = entries[context.datasetIndex][1];
                    return series.labels?.[context.raw - (series.min ?? 1)] || '';
                }
            }}}
        }
    });
}
