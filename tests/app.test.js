// The front end has no bundler and no framework: static/app.js is a classic
// script that exports its pure helpers only when `module` exists (i.e. here).
const test = require('node:test');
const assert = require('node:assert/strict');

const {esc, fmtGpa, semesterOf, orderCourses} = require('../static/app.js');

const course = (semester, course_id) => ({semester, course_id});
const idsOf = (courses) => courses.map((c) => c.course_id);

test('orderCourses follows the server semester list, newest first', () => {
    // Arrange - analyzer.py orders per_semester ascending; 99 precedes 100.
    const semesters = ['99-1', '99-2', '100-1'];
    const courses = [course('99-1', 'A'), course('100-1', 'B'), course('99-2', 'C')];

    // Act
    const ordered = orderCourses(courses, semesters);

    // Assert
    assert.deepEqual(idsOf(ordered), ['B', 'C', 'A']);
});

test('orderCourses breaks ties within a semester by course id', () => {
    const semesters = ['113-1'];
    const courses = [course('113-1', 'ZZ999'), course('113-1', 'AA100')];

    const ordered = orderCourses(courses, semesters);

    assert.deepEqual(idsOf(ordered), ['AA100', 'ZZ999']);
});

test('orderCourses keeps labels with identical digit runs apart', () => {
    // A digit-only comparator scored '113/1' and '113-1' equal and then fell
    // through to course_id, interleaving two different semesters.
    const semesters = ['113/1', '113-1'];
    const courses = [course('113-1', 'ZZ999'), course('113/1', 'AA100')];

    const ordered = orderCourses(courses, semesters);

    assert.deepEqual(idsOf(ordered), ['ZZ999', 'AA100']);
});

test('orderCourses handles full-width digits the server understood', () => {
    // Python's \d is Unicode-aware; JS /\d/ without the u flag is not, so a
    // client-side parse used to sort this semester below every ASCII one.
    const semesters = ['１１３學年度第１學期', '114-1'];
    const courses = [course('１１３學年度第１學期', 'OLD'), course('114-1', 'NEW')];

    const ordered = orderCourses(courses, semesters);

    assert.deepEqual(idsOf(ordered), ['NEW', 'OLD']);
});

test('orderCourses sinks a course whose semester the server never reported', () => {
    const semesters = ['113-1'];
    const courses = [course('unknown', 'X'), course('113-1', 'Y')];

    const ordered = orderCourses(courses, semesters);

    assert.deepEqual(idsOf(ordered), ['Y', 'X']);
});

test('orderCourses returns an empty list for missing input', () => {
    assert.deepEqual(orderCourses(), []);
});

test('orderCourses does not mutate its input', () => {
    const courses = [course('99-1', 'A'), course('100-1', 'B')];

    orderCourses(courses, ['99-1', '100-1']);

    assert.deepEqual(idsOf(courses), ['A', 'B']);
});

test('semesterOf trims and normalizes every falsy semester the same way', () => {
    assert.equal(semesterOf({semester: ' 113-1 '}), '113-1');
    assert.equal(semesterOf({semester: null}), '');
    assert.equal(semesterOf({}), '');
    // 0 must not collapse to '' the way `semester || ''` did - it is a real key.
    assert.equal(semesterOf({semester: 0}), '0');
});

test('esc escapes every character that could break out of an attribute or tag', () => {
    assert.equal(esc(`<a href="x">&'`), '&lt;a href=&quot;x&quot;&gt;&amp;&#39;');
    assert.equal(esc(null), '');
    assert.equal(esc(undefined), '');
});

test('fmtGpa renders two decimals and an em dash for no grade', () => {
    assert.equal(fmtGpa(3.5), '3.50');
    assert.equal(fmtGpa(null), '—');
    assert.equal(fmtGpa(undefined), '—');
});
