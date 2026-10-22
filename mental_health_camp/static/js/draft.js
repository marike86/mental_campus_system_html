function readAnswerDraft(key) {
    try {
        const value = JSON.parse(localStorage.getItem(key));
        return value && typeof value === 'object' && !Array.isArray(value) ? value : null;
    } catch (_) { return null; }
}
function writeAnswerDraft(key, answers) {
    if (!key) return;
    try { localStorage.setItem(key, JSON.stringify(answers)); } catch (_) {}
}
function saveDraft(formId) {
    const form = document.getElementById('form-' + formId);
    if (!form) return;
    const answers = {};
    form.querySelectorAll('[name^="q_"]').forEach(el => {
        const id = el.name.slice(2);
        if (el.type === 'checkbox') {
            answers[id] ??= [];
            if (el.checked) answers[id].push(el.value);
        } else if (el.type !== 'radio' || el.checked) answers[id] = el.value;
    });
    writeAnswerDraft(form.dataset.draftKey, answers);
}
function initFormDraft(formId) {
    const form = document.getElementById('form-' + formId);
    if (!form) return;
    const answers = readAnswerDraft(form.dataset.draftKey);
    if (!answers) return;
    form.querySelectorAll('[name^="q_"]').forEach(el => {
        const value = answers[el.name.slice(2)];
        if (value === undefined) return;
        if (el.type === 'checkbox') el.checked = Array.isArray(value) && value.includes(el.value);
        else if (el.type === 'radio') el.checked = String(value) === el.value;
        else el.value = value;
    });
}
