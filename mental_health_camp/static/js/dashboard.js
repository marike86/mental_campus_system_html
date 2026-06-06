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
        if (day.status === 'completed') {
            bgClass = 'bg-brand-800';
            textColor = 'text-white';
        } else if (day.status === 'missed') {
            bgClass = 'bg-red-100';
            textColor = 'text-red-400';
        } else {
            bgClass = 'bg-gray-100';
            textColor = 'text-gray-400';
        }
        html += '<div class="aspect-square rounded-lg flex items-center justify-center text-xs font-medium ' + bgClass + ' ' + textColor + ' cursor-default" title="第' + day.day + '天 - ' + (day.status === 'completed' ? '已完成' : day.status === 'missed' ? '未完成' : '未到来') + '">' + day.day + '</div>';
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
    if (!seriesData || Object.keys(seriesData).length === 0) return;
    var qid = Object.keys(seriesData)[0];
    var series = seriesData[qid];
    var labels = series.data.map(function(d) { return '第' + d.day + '天'; });
    var values = series.data.map(function(d) { return d.value; });
    var canvas = document.getElementById(canvasId);
    if (!canvas) return;
    var ctx = canvas.getContext('2d');
    if (typeof Chart === 'undefined') return;
    new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: series.label,
                data: values,
                borderColor: '#9c0c13',
                backgroundColor: 'rgba(156,12,19,0.1)',
                fill: true,
                tension: 0.3,
                pointBackgroundColor: '#9c0c13',
                pointBorderColor: '#fff',
                pointBorderWidth: 2,
                pointRadius: 5,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    min: 0,
                    max: 6,
                    ticks: { stepSize: 1, font: { size: 12 } },
                    grid: { color: 'rgba(0,0,0,0.05)' }
                },
                x: {
                    ticks: { font: { size: 12 } },
                    grid: { display: false }
                }
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        afterLabel: function(ctx) {
                            var idx = ctx.dataIndex;
                            var dayVal = series.data[idx].value;
                            var labelsList = series.labels;
                            if (labelsList && labelsList.length >= dayVal) {
                                return labelsList[dayVal - 1];
                            }
                            return '';
                        }
                    }
                }
            }
        }
    });
}
