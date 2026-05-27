function getDraftKey(formId) {
    return 'draft_' + formId;
}

function saveDraft(formId) {
    var form = document.getElementById('form-' + formId);
    if (!form) return;
    var data = {};
    var inputs = form.querySelectorAll('input, textarea, select');
    inputs.forEach(function(el) {
        if (el.type === 'checkbox') {
            if (!data[el.name]) data[el.name] = [];
            if (el.checked) data[el.name].push(el.value);
        } else if (el.type === 'radio') {
            if (el.checked) data[el.name] = el.value;
        } else {
            data[el.name] = el.value;
        }
    });
    localStorage.setItem(getDraftKey(formId), JSON.stringify(data));
}

function restoreDraft(formId) {
    var raw = localStorage.getItem(getDraftKey(formId));
    if (!raw) return;
    var data;
    try { data = JSON.parse(raw); } catch(e) { return; }
    var form = document.getElementById('form-' + formId);
    if (!form) return;
    Object.keys(data).forEach(function(name) {
        var value = data[name];
        var el = form.querySelector('[name="' + name + '"]');
        if (!el) return;
        if (el.type === 'checkbox') {
            var group = form.querySelectorAll('[name="' + name + '"]');
            group.forEach(function(cb) {
                cb.checked = Array.isArray(value) && value.includes(cb.value);
            });
        } else if (el.type === 'radio') {
            var radio = form.querySelector('[name="' + name + '"][value="' + value + '"]');
            if (radio) radio.checked = true;
        } else {
            el.value = value;
        }
    });
}

function clearDraft(formId) {
    localStorage.removeItem(getDraftKey(formId));
}

function initFormDraft(formId) {
    restoreDraft(formId);
    var form = document.getElementById('form-' + formId);
    if (!form) return;
    form.addEventListener('submit', function() {
        clearDraft(formId);
    });
}
