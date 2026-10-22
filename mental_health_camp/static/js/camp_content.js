class CampStepManager {
    constructor(options) {
        this.questions = options.questions;
        this.enrollmentId = options.enrollmentId;
        this.dayNumber = options.dayNumber;
        this.formAction = options.formAction;
        this.csrfToken = options.csrfToken;
        this.versionId = options.versionId;
        this.draftKey = options.draftKey;
        this.currentStep = 0;
        this.steps = this._buildSteps();
        this.answers = (typeof readAnswerDraft === "function" ? readAnswerDraft(this.draftKey) : null) || options.initialAnswers || {};
        this.verifiedSteps = new Set();
        this._render();
    }

    _buildSteps() {
        var steps = [];
        var currentReading = null;
        var currentQuestions = [];
        for (var i = 0; i < this.questions.length; i++) {
            var q = this.questions[i];
            if (q.type === 'reading') {
                if (currentReading || currentQuestions.length > 0) {
                    steps.push({ type: 'section', reading: currentReading, questions: currentQuestions });
                }
                currentReading = q;
                currentQuestions = [];
            } else {
                currentQuestions.push(q);
            }
        }
        if (currentReading || currentQuestions.length > 0) {
            steps.push({ type: 'section', reading: currentReading, questions: currentQuestions });
        }
        if (steps.length === 0 && this.questions.length > 0) {
            steps.push({ type: 'section', reading: null, questions: this.questions });
        }
        return steps;
    }

    _render() {
        var container = document.getElementById('camp-content-container');
        if (!container) return;
        var step = this.steps[this.currentStep];
        if (!step) { this._renderComplete(); return; }
        var html = '';
        html += this._renderProgress();
        if (step.reading) {
            html += this._renderReading(step.reading);
        }
        if (step.questions.length > 0) {
            html += this._renderQuestions(step.questions);
        }
        container.innerHTML = html;
        this._bindEvents();
    }

    _renderProgress() {
        var total = this.steps.length;
        var current = this.currentStep + 1;
        var pct = Math.round((current / total) * 100);
        var html = '<div class="mb-6">';
        html += '<div class="flex items-center justify-between mb-2">';
        html += '<span class="text-sm font-medium text-gray-700">步骤 ' + current + ' / ' + total + '</span>';
        html += '<span class="text-sm text-gray-500">' + pct + '%</span>';
        html += '</div>';
        html += '<div class="w-full bg-gray-200 rounded-full h-2">';
        html += '<div class="bg-brand-800 h-2 rounded-full transition-all duration-500" style="width:' + pct + '%"></div>';
        html += '</div>';
        html += '</div>';
        return html;
    }

    _renderReading(reading) {
        var html = '<div class="bg-brand-50 border border-brand-200 rounded-xl p-6 mb-6">';
        html += '<div class="flex items-center mb-3">';
        html += '<div class="w-8 h-8 bg-brand-100 rounded-lg flex items-center justify-center mr-3">';
        html += '<svg class="w-4 h-4 text-brand-800" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"></path></svg>';
        html += '</div>';
        html += '<h3 class="text-lg font-semibold text-gray-900">' + this._esc(reading.label || '阅读材料') + '</h3>';
        html += '</div>';
        html += '<div class="prose prose-sm max-w-none text-gray-700 leading-relaxed whitespace-pre-wrap">' + this._esc(reading.content || '') + '</div>';
        html += '<div class="mt-4 pt-4 border-t border-brand-200">';
        html += '<p class="text-sm text-brand-700 flex items-center">';
        html += '<svg class="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>';
        html += '请仔细阅读以上内容后继续';
        html += '</p></div></div>';
        html += '<div class="text-center">';
        html += '<button type="button" onclick="window.campManager.showQuestions()" class="bg-brand-800 hover:bg-brand-700 text-white px-6 py-2.5 rounded-lg font-medium transition-colors inline-flex items-center">';
        html += '我已阅读，继续答题 ';
        html += '<svg class="w-4 h-4 ml-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path></svg>';
        html += '</button></div>';
        return html;
    }

    _renderQuestions(questions) {
        var verified = this._isCurrentStepVerified();
        var html = '<div id="questions-area" class="space-y-5">';
        for (var i = 0; i < questions.length; i++) {
            var q = questions[i];
            html += '<div data-qid="' + q.id + '" class="border border-gray-200 rounded-xl p-5">';
            html += '<label class="block text-sm font-medium text-gray-700 mb-3">' + this._esc(q.label) + '</label>';
            if (q.type === 'single') {
                html += this._renderSingle(q, verified);
            } else if (q.type === 'multiple') {
                html += this._renderMultiple(q, verified);
            } else if (q.type === 'text') {
                html += this._renderText(q, verified);
            } else if (q.type === 'likert') {
                html += this._renderLikert(q, verified);
            }
            if (q.correct !== undefined && q.correct !== null) {
                html += '<div id="feedback-' + q.id + '" class="mt-2 text-sm hidden"></div>';
            }
            html += '</div>';
        }
        html += '</div>';
        html += '<div class="mt-6 text-center">';
        var hasCorrectable = questions.some(function(q) { return q.correct !== undefined && q.correct !== null; });
        if (hasCorrectable && !verified) {
            html += '<button type="button" onclick="window.campManager.verifyCurrent()" class="bg-brand-800 hover:bg-brand-700 text-white px-6 py-2.5 rounded-lg font-medium transition-colors inline-flex items-center mr-3">';
            html += '<svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>';
            html += '验证答案</button>';
        }
        if (verified || !hasCorrectable) {
            html += '<button type="button" onclick="window.campManager.nextStep()" class="bg-brand-800 hover:bg-brand-700 text-white px-6 py-2.5 rounded-lg font-medium transition-colors inline-flex items-center">';
            html += this.currentStep < this.steps.length - 1 ? '继续下一段 ' : '完成并提交 ';
            html += '<svg class="w-4 h-4 ml-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path></svg>';
            html += '</button>';
        }
        html += '</div>';
        return html;
    }

    _renderSingle(q, disabled) {
        var html = '<div class="space-y-2">';
        for (var i = 0; i < (q.options || []).length; i++) {
            var opt = q.options[i];
            var checked = this.answers[q.id] === opt;
            html += '<label class="flex items-center space-x-3 p-3 rounded-lg border border-gray-200 hover:border-brand-300 hover:bg-brand-50 cursor-pointer transition-colors">';
            html += '<input type="radio" name="q_' + q.id + '" value="' + this._esc(opt) + '"' + (checked ? ' checked' : '') + (disabled ? ' disabled' : '') + ' onchange="window.campManager.setAnswer(\'' + q.id + '\', this.value)" class="w-4 h-4 text-brand-800 focus:ring-brand-600 border-gray-300">';
            html += '<span class="text-sm text-gray-700">' + this._esc(opt) + '</span>';
            html += '</label>';
        }
        html += '</div>';
        return html;
    }

    _renderMultiple(q, disabled) {
        var html = '<div class="space-y-2">';
        var selected = this.answers[q.id] || [];
        for (var i = 0; i < (q.options || []).length; i++) {
            var opt = q.options[i];
            var checked = selected.indexOf(opt) !== -1;
            html += '<label class="flex items-center space-x-3 p-3 rounded-lg border border-gray-200 hover:border-brand-300 hover:bg-brand-50 cursor-pointer transition-colors">';
            html += '<input type="checkbox" name="q_' + q.id + '" value="' + this._esc(opt) + '"' + (checked ? ' checked' : '') + (disabled ? ' disabled' : '') + ' onchange="window.campManager.toggleMulti(\'' + q.id + '\', this.value, this.checked)" class="w-4 h-4 text-brand-800 focus:ring-brand-600 border-gray-300 rounded">';
            html += '<span class="text-sm text-gray-700">' + this._esc(opt) + '</span>';
            html += '</label>';
        }
        html += '</div>';
        return html;
    }

    _renderText(q, disabled) {
        var val = this.answers[q.id] || '';
        return '<textarea rows="3" ' + (disabled ? 'disabled ' : '') + 'oninput="window.campManager.setAnswer(\'' + q.id + '\', this.value)" class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-brand-600 focus:border-brand-600 outline-none transition-colors text-sm resize-none" placeholder="请输入你的回答">' + this._esc(val) + '</textarea>';
    }

    _renderLikert(q, disabled) {
        var min = q.min ?? 1;
        var max = q.max ?? 5;
        var labels = q.labels || [];
        var selected = Number(this.answers[q.id] ?? -1);
        var html = '<div class="flex items-center justify-between space-x-2 mt-2">';
        for (var i = min; i <= max; i++) {
            var isActive = selected === i;
            html += '<div class="flex flex-col items-center">';
            html += '<button type="button" ' + (disabled ? 'disabled ' : '') + 'onclick="window.campManager.setAnswer(\'' + q.id + '\', ' + i + '); window.campManager.updateLikertUI(\'' + q.id + '\', ' + i + ')" id="likert_camp_' + q.id + '_' + i + '" class="w-10 h-10 rounded-full border-2 ' + (isActive ? 'border-brand-800 bg-brand-800 text-white' : 'border-gray-300 text-gray-500') + ' flex items-center justify-center text-sm font-medium cursor-pointer hover:border-brand-400 transition-all">';
            html += i + '</button>';
            if (labels[i - min]) {
                html += '<span class="text-xs text-gray-500 mt-1">' + this._esc(labels[i - min]) + '</span>';
            }
            html += '</div>';
        }
        html += '</div>';
        return html;
    }

    _renderComplete() {
        var container = document.getElementById('camp-content-container');
        if (!container) return;
        var html = '<div class="text-center py-8">';
        html += '<div class="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">';
        html += '<svg class="w-8 h-8 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>';
        html += '</div>';
        html += '<h2 class="text-xl font-bold text-gray-900 mb-2">所有步骤已完成！</h2>';
        html += '<p class="text-gray-500 mb-6">点击下方按钮提交你的回答</p>';
        html += '<form id="camp-submit-form" method="POST" action="' + this.formAction + '">';
        html += '<input type="hidden" name="csrf_token" value="' + this._esc(this.csrfToken) + '">';
        html += '<input type="hidden" name="version_id" value="' + this.versionId + '">';
        for (var key in this.answers) {
            var val = this.answers[key];
            if (Array.isArray(val)) {
                for (var i = 0; i < val.length; i++) {
                    html += '<input type="hidden" name="q_' + key + '" value="' + this._esc(val[i]) + '">';
                }
            } else if (val !== null && val !== undefined) {
                html += '<input type="hidden" name="q_' + key + '" value="' + this._esc(String(val)) + '">';
            }
        }
        html += '<button type="submit" class="bg-brand-800 hover:bg-brand-700 text-white px-8 py-3 rounded-lg font-medium transition-colors inline-flex items-center">';
        html += '<svg class="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>';
        html += '提交表单</button>';
        html += '</form></div>';
        container.innerHTML = html;
    }

    showQuestions() {
        var area = document.getElementById('questions-area');
        if (area) return;
        this._render();
    }

    setAnswer(qid, value) {
        this.answers[qid] = value;
        if (typeof writeAnswerDraft === "function") writeAnswerDraft(this.draftKey, this.answers);
        this.verifiedSteps.delete(this.currentStep);
    }

    toggleMulti(qid, value, checked) {
        if (!this.answers[qid]) this.answers[qid] = [];
        var arr = this.answers[qid];
        var idx = arr.indexOf(value);
        if (checked && idx === -1) { arr.push(value); }
        else if (!checked && idx !== -1) { arr.splice(idx, 1); }
        if (typeof writeAnswerDraft === 'function') writeAnswerDraft(this.draftKey, this.answers);
        this.verifiedSteps.delete(this.currentStep);
    }

    updateLikertUI(qid, val) {
        var question = this.questions.find(q => q.id === qid);
        var min = question?.min ?? 1, max = question?.max ?? 5;
        for (var i = min; i <= max; i++) {
            var btn = document.getElementById('likert_camp_' + qid + '_' + i);
            if (!btn) continue;
            if (i === val) {
                btn.classList.remove('border-gray-300', 'text-gray-500');
                btn.classList.add('border-brand-800', 'bg-brand-800', 'text-white');
            } else {
                btn.classList.remove('border-brand-800', 'bg-brand-800', 'text-white');
                btn.classList.add('border-gray-300', 'text-gray-500');
            }
        }
    }

    async verifyCurrent() {
        var step = this.steps[this.currentStep];
        if (!step) return;
        for (var i = 0; i < step.questions.length; i++) {
            var q = step.questions[i];
            if (q.correct === undefined || q.correct === null) continue;
            var answer = this.answers[q.id];
            if (answer === undefined || answer === null || answer === '') {
                this._showFeedback(q.id, false, '请先作答');
                return;
            }
            try {
                var resp = await fetch('/user/api/verify-answer', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': this.csrfToken },
                    body: JSON.stringify({
                        enrollment_id: this.enrollmentId,
                        day_number: this.dayNumber,
                        question_id: q.id,
                        answer: answer
                    })
                });
                var data = await resp.json();
                this._showFeedback(q.id, data.correct, data.message);
                if (!data.correct) return;
            } catch (e) {
                this._showFeedback(q.id, false, '验证失败，请重试');
                return;
            }
        }
        this.verifiedSteps.add(this.currentStep);
        this._render();
    }

    _showFeedback(qid, correct, message) {
        var el = document.getElementById('feedback-' + qid);
        if (!el) return;
        el.classList.remove('hidden');
        if (correct) {
            el.className = 'mt-2 text-sm text-green-700 bg-green-50 border border-green-200 rounded-lg p-2';
            el.innerHTML = '✓ ' + this._esc(message);
        } else {
            el.className = 'mt-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg p-2';
            el.innerHTML = '✗ ' + this._esc(message);
        }
    }

    _isCurrentStepVerified() {
        return this.verifiedSteps.has(this.currentStep);
    }

    nextStep() {
        if (this.currentStep < this.steps.length - 1) {
            this.currentStep++;
            this._render();
            window.scrollTo({ top: 0, behavior: 'smooth' });
        } else {
            this._renderComplete();
        }
    }

    _bindEvents() {}

    _esc(str) {
        if (str === null || str === undefined) return '';
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
}
