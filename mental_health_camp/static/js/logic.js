function initConditionalLogic(questionsJson) {
    var questions;
    try {
        questions = typeof questionsJson === 'string' ? JSON.parse(questionsJson) : questionsJson;
    } catch(e) {
        return;
    }
    if (!Array.isArray(questions)) return;

    var conditionMap = {};
    questions.forEach(function(q) {
        if (q.condition && q.condition.question_id) {
            conditionMap[q.id] = q.condition;
        }
    });

    if (Object.keys(conditionMap).length === 0) return;

    function getAnswer(questionId) {
        var name = 'q_' + questionId;
        var radios = document.querySelectorAll('input[type="radio"][name="' + name + '"]');
        for (var i = 0; i < radios.length; i++) {
            if (radios[i].checked) return radios[i].value;
        }
        var checkboxes = document.querySelectorAll('input[type="checkbox"][name="' + name + '"]');
        var checked = [];
        for (var j = 0; j < checkboxes.length; j++) {
            if (checkboxes[j].checked) checked.push(checkboxes[j].value);
        }
        if (checked.length > 0) return checked;
        var textEl = document.querySelector('textarea[name="' + name + '"], input[type="text"][name="' + name + '"]');
        if (textEl) return textEl.value;
        return null;
    }

    function evaluateCondition(cond) {
        var answer = getAnswer(cond.question_id);
        if (answer === null || answer === undefined || answer === '') return false;
        var op = cond.operator || 'equals';
        var target = cond.value;
        if (Array.isArray(answer)) {
            if (op === 'includes') return answer.indexOf(target) !== -1;
            if (op === 'equals') return answer.indexOf(target) !== -1;
            return false;
        }
        if (op === 'equals') return answer === target;
        if (op === 'not_equals') return answer !== target;
        if (op === 'includes') return String(answer).indexOf(target) !== -1;
        return false;
    }

    function updateVisibility() {
        Object.keys(conditionMap).forEach(function(qid) {
            var cond = conditionMap[qid];
            var questionEl = document.querySelector('[data-question-id="' + qid + '"]');
            if (!questionEl) return;
            var visible = evaluateCondition(cond);
            if (visible) {
                questionEl.classList.remove('hidden');
                questionEl.removeAttribute('disabled');
            } else {
                questionEl.classList.add('hidden');
                var inputs = questionEl.querySelectorAll('input, textarea, select');
                inputs.forEach(function(inp) {
                    if (inp.type === 'radio' || inp.type === 'checkbox') {
                        inp.checked = false;
                    } else {
                        inp.value = '';
                    }
                });
            }
        });
    }

    document.querySelectorAll('input[type="radio"], input[type="checkbox"]').forEach(function(el) {
        el.addEventListener('change', updateVisibility);
    });
    document.querySelectorAll('textarea, input[type="text"]').forEach(function(el) {
        el.addEventListener('input', updateVisibility);
    });

    updateVisibility();
}
