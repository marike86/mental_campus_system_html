// Run with: node --test test_camp_content.js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

test('course verification and final form carry the page CSRF token', async () => {
    const container = { innerHTML: '' };
    let verification;
    const context = vm.createContext({
        document: { getElementById: () => container },
        fetch: async (url, options) => {
            verification = { url, options };
            return { json: async () => ({ correct: true, message: 'OK' }) };
        },
    });
    const source = fs.readFileSync(path.join(__dirname, 'static/js/camp_content.js'), 'utf8');
    vm.runInContext(source + '\nthis.Manager = CampStepManager;', context);
    // Use the real workflow methods while leaving layout rendering to page templates.
    context.Manager.prototype._render = function () {};
    context.Manager.prototype._esc = value => String(value);
    context.Manager.prototype._showFeedback = function () {};
    const manager = new context.Manager({
        questions: [{ id: 'choice', type: 'single', correct: 'A' }],
        enrollmentId: 1, dayNumber: 1, formAction: '/user/form/1/1', csrfToken: 'page-token',
    });
    manager.answers.choice = 'A';
    await manager.verifyCurrent();
    assert.equal(verification.url, '/user/api/verify-answer');
    assert.equal(verification.options.headers['X-CSRF-Token'], 'page-token');
    assert.equal(JSON.parse(verification.options.body).answer, 'A');
    manager._renderComplete();
    assert.match(container.innerHTML, /name="csrf_token" value="page-token"/);
    assert.match(container.innerHTML, /name="q_choice" value="A"/);
});
