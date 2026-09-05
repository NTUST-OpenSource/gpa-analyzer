const GRADE_ORDER = ['A+', 'A', 'A-', 'B+', 'B', 'B-', 'C+', 'C', 'C-', 'D', 'E', 'X'];

const GRADE_COLORS = {
    'A+': '#2ca02c', 'A': '#98df8a', 'A-': '#56b456',
    'B+': '#1f77b4', 'B': '#aec7e8', 'B-': '#4a9fd8',
    'C+': '#ff7f0e', 'C': '#ffbb78', 'C-': '#ff9f49',
    'D': '#d62728', 'E': '#ff9896', 'X': '#9467bd'
};

const fmtGpa = (v) => (v === null || v === undefined) ? '—' : Number(v).toFixed(2);

const color = (letter, alpha = 1.0) => GRADE_COLORS[letter]
    ? `${GRADE_COLORS[letter]}${Math.floor(alpha * 255).toString(16).padStart(2, '0')}`
    : '#888888';

const esc = (v) => (v === null || v === undefined) ? '' : String(v).replace(
    /[&<>"']/g,
    (ch) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[ch])
);

function renderLegend(containerId, gradeMap) {
    const tbody = document.createElement('tbody');

    for (const letter of GRADE_ORDER) {
        const row = gradeMap[letter];
        if (!row) continue;
        const [low, high] = row.percent_range || [null, null];

        const tr = document.createElement('tr');
        tr.className = 'border-t border-gray-100';

        const nameCell = document.createElement('td');
        nameCell.className = 'py-1 pr-2 font-medium text-gray-900 flex items-center';
        const swatch = document.createElement('span');
        swatch.className = 'inline-block w-3 h-3 mr-2 rounded-sm';
        // Set through CSSOM: a style attribute would be blocked by style-src 'self'.
        swatch.style.backgroundColor = color(letter);
        nameCell.append(swatch, letter);

        const gpaCell = document.createElement('td');
        gpaCell.className = 'py-1 pr-2 text-gray-700';
        gpaCell.textContent = row.gpa;

        const rangeCell = document.createElement('td');
        rangeCell.className = 'py-1 text-gray-500';
        rangeCell.textContent = (low === null || high === null) ? '—' : `${low}-${high}`;

        tr.append(nameCell, gpaCell, rangeCell);
        tbody.appendChild(tr);
    }

    const table = document.createElement('table');
    table.className = 'min-w-full';
    table.appendChild(tbody);
    document.getElementById(containerId).replaceChildren(table);
}

function renderStudentInfo(info) {
    if (!info || !info.student_id) return;
    const headerInfo = document.getElementById('headerStudentInfo');
    headerInfo.classList.remove('hidden');
    headerInfo.classList.add('flex');
    document.getElementById('headerName').textContent = info.name || '';
    document.getElementById('headerId').textContent = info.student_id;
    document.getElementById('headerClass').textContent = info.class_name || '';
}

function renderCreditsSummary(summary) {
    const summaryDiv = document.getElementById('creditsSummary');
    if (!summary || !summary.earned_credits) {
        summaryDiv.innerHTML = `<p class="text-gray-500">無學分統計資料</p>`;
        return;
    }
    const earned = summary.earned_credits.total || 0;
    const inProgress = (summary.in_progress_credits || {}).total || 0;
    const total = (summary.total_credits || {}).total || 0;
    document.getElementById('overallCredits').textContent = total;
    summaryDiv.innerHTML = `
        <p><strong>已實得學分數:</strong> ${esc(earned)}</p>
        <p><strong>修習中學分數:</strong> ${esc(inProgress)}</p>
        <p><strong>合計學分數:</strong> ${esc(total)}</p>
    `;
}

function renderRankings(rankings) {
    const rankingBody = document.getElementById('rankingBody');
    const rankingCards = document.getElementById('rankingCards');
    rankingBody.replaceChildren();
    rankingCards.replaceChildren();

    if (!rankings || rankings.length === 0) {
        rankingBody.innerHTML = `<tr><td colspan="5" class="px-3 py-4 text-center text-gray-500">無排名資料</td></tr>`;
        rankingCards.innerHTML = `<p class="text-center text-gray-500 py-4">無排名資料</p>`;
        return;
    }

    for (const r of rankings) {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td class="px-3 py-2 text-gray-700">${esc(r.semester)}</td>
            <td class="px-3 py-2 text-gray-700">${esc(r.class_rank)}</td>
            <td class="px-3 py-2 text-gray-700">${esc(r.department_rank)}</td>
            <td class="px-3 py-2 text-gray-700">${esc(r.cumulative_class_rank)}</td>
            <td class="px-3 py-2 text-gray-700">${esc(r.cumulative_department_rank)}</td>
        `;
        rankingBody.appendChild(tr);

        const card = document.createElement('div');
        card.className = 'bg-gray-50 p-3 rounded-lg border border-gray-100 text-sm space-y-1';
        card.innerHTML = `
            <div class="flex justify-between font-bold text-gray-900 border-b pb-1 mb-1">
                <span>${esc(r.semester)}</span>
            </div>
            <div class="grid grid-cols-2 gap-2">
                <div><span class="text-gray-500">班排:</span> ${esc(r.class_rank)}</div>
                <div><span class="text-gray-500">系排:</span> ${esc(r.department_rank)}</div>
                <div><span class="text-gray-500">歷年班排:</span> ${esc(r.cumulative_class_rank)}</div>
                <div><span class="text-gray-500">歷年系排:</span> ${esc(r.cumulative_department_rank)}</div>
            </div>
        `;
        rankingCards.appendChild(card);
    }
}

const TAB_BASE = 'whitespace-nowrap px-3 py-2 -mb-px text-sm font-medium border-b-2 transition-colors'
    + ' focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-indigo-500';
const TAB_ACTIVE = 'text-indigo-600 border-indigo-600';
const TAB_IDLE = 'text-gray-500 border-transparent hover:text-gray-700 hover:border-gray-300';

// A course whose 學年期 cell came back blank still has to land on a labelled tab.
const UNLABELLED_SEMESTER = '未分類';
const SEMESTER_PARAM = 'semester';
const NO_SEMESTER_RANK = -1;

const semesterOf = (course) => String(course.semester ?? '').trim();

// analyzer.py already ordered the semesters and app.py ships that list, so index
// into it. A second ordering implementation over here is what 66fa291 had to fix,
// and it can only ever drift again (Unicode digits, tiebreaks, null semesters).
function orderCourses(courses = [], semesters = []) {
    const rank = new Map(semesters.map((s, i) => [s, i]));
    // Newest semester first, as the table has always been; unknown semesters sink.
    return [...courses].sort((a, b) =>
        (rank.get(semesterOf(b)) ?? NO_SEMESTER_RANK) - (rank.get(semesterOf(a)) ?? NO_SEMESTER_RANK) ||
        String(a.course_id ?? '').localeCompare(String(b.course_id ?? ''))
    );
}

function renderCourseRows(courses = []) {
    const tbody = document.getElementById('courseBody');
    const courseCards = document.getElementById('courseCards');
    tbody.replaceChildren();
    courseCards.replaceChildren();

    if (courses.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="px-3 py-4 text-center text-gray-500">無課程資料</td></tr>`;
        courseCards.innerHTML = `<p class="text-center text-gray-500 py-4">無課程資料</p>`;
        return;
    }

    for (const c of courses) {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td class="px-3 py-2 text-gray-700">${esc(c.semester)}</td>
            <td class="px-3 py-2 text-gray-700">${esc(c.course_id)}</td>
            <td class="px-3 py-2 text-gray-900 font-medium">${esc(c.course_name)}</td>
            <td class="px-3 py-2 tabular-nums">${esc(c.credits)}</td>
            <td class="px-3 py-2">${esc(c.grade)}</td>
            <td class="px-3 py-2 text-gray-700">${esc(c.dimension || '-')}</td>
        `;
        tbody.appendChild(tr);

        const card = document.createElement('div');
        card.className = 'bg-gray-50 p-4 rounded-lg border border-gray-100 space-y-2';
        card.innerHTML = `
            <div class="flex justify-between items-start">
                <div>
                    <div class="text-[10px] text-gray-500">${esc(c.semester)} | ${esc(c.course_id)}</div>
                    <div class="font-bold text-gray-900 text-sm">${esc(c.course_name)}</div>
                </div>
                <div class="text-base font-bold text-indigo-600 ml-2">${esc(c.grade)}</div>
            </div>
            <div class="flex justify-between text-xs text-gray-600 border-t pt-2 mt-1">
                <span>學分: ${esc(c.credits)}</span>
                <span>向度: ${esc(c.dimension || '-')}</span>
            </div>
        `;
        courseCards.appendChild(card);
    }
}

function renderCourses(courses = [], semesters = []) {
    const tabs = document.getElementById('semesterTabs');
    const panel = document.getElementById('coursePanel');

    // Everything the render needs is computed before the first DOM write, so a bad
    // payload can no longer leave an empty tab strip standing over stale rows.
    const sorted = orderCourses(courses, semesters);

    // One semester needs no tabs: "全部" would show exactly the same rows.
    if (semesters.length < 2) {
        tabs.replaceChildren();
        tabs.classList.add('hidden');
        tabs.classList.remove('flex');
        for (const attr of ['role', 'aria-labelledby', 'tabindex']) panel.removeAttribute(attr);
        document.getElementById('courseScope').textContent = '';
        renderCourseRows(sorted);
        return;
    }

    // `null` is the "all semesters" key. Holding it outside the semester value space
    // means no scraped 學年期 string can collide with it. Newest first, so the tab
    // that opens by default sits next to 全部 rather than at the far end of the strip.
    const newestFirst = [...semesters].reverse();
    const entries = [[null, '全部'], ...newestFirst.map((s) => [s, s || UNLABELLED_SEMESTER])];
    const tabButtons = entries.map(([key, label], i) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.id = `semesterTab-${i}`;
        button.textContent = label;
        button.setAttribute('role', 'tab');
        button.setAttribute('aria-controls', 'coursePanel');
        return {key, button};
    });

    const select = (key, {fromUser = false} = {}) => {
        const active = tabButtons.find((tab) => tab.key === key) ?? tabButtons[0];

        for (const tab of tabButtons) {
            const isActive = tab === active;
            tab.button.className = `${TAB_BASE} ${isActive ? TAB_ACTIVE : TAB_IDLE}`;
            tab.button.setAttribute('aria-selected', String(isActive));
            // Roving tabindex: the strip is one stop, not one per semester.
            tab.button.tabIndex = isActive ? 0 : -1;
        }
        panel.setAttribute('aria-labelledby', active.button.id);
        renderCourseRows(active.key === null ? sorted : sorted.filter((c) => semesterOf(c) === active.key));
        // The credit summary and all three charts above stay all-time, so the list
        // has to say out loud that it is not.
        document.getElementById('courseScope').textContent = `· ${active.button.textContent}`;

        // Only an explicit choice goes in the URL, so a plain load stays clean and
        // still opens on the newest semester while a shared link keeps its tab. The
        // one exception is a stale link (?semester=113-1 after the year rolled over):
        // that param has to go, or the URL claims a semester the page is not showing.
        const url = new URL(window.location.href);
        if (fromUser && active.key !== null) url.searchParams.set(SEMESTER_PARAM, active.key);
        else if (fromUser || url.searchParams.get(SEMESTER_PARAM) !== active.key) {
            url.searchParams.delete(SEMESTER_PARAM);
        }
        if (url.href !== window.location.href) history.replaceState(null, '', url);

        if (!fromUser) return;
        active.button.focus();
        // A shorter tab shrinks the document, and the browser clamps the scroll
        // offset to the new maximum - which lands the reader on the footer.
        if (tabs.getBoundingClientRect().top < 0) tabs.scrollIntoView({block: 'start'});
    };

    const ARROW_STEP = {ArrowLeft: -1, ArrowRight: 1};
    tabButtons.forEach((tab, i) => {
        tab.button.addEventListener('click', () => select(tab.key, {fromUser: true}));
        tab.button.addEventListener('keydown', (event) => {
            const step = ARROW_STEP[event.key];
            const target = step === undefined
                ? {Home: tabButtons[0], End: tabButtons.at(-1)}[event.key]
                : tabButtons[(i + step + tabButtons.length) % tabButtons.length];
            if (!target) return;
            event.preventDefault();
            select(target.key, {fromUser: true});
        });
    });

    panel.setAttribute('role', 'tabpanel');
    panel.tabIndex = 0;
    tabs.replaceChildren(...tabButtons.map((tab) => tab.button));
    // Both classes set `display`, so they are swapped rather than combined.
    tabs.classList.remove('hidden');
    tabs.classList.add('flex');

    // The newest semester is what the page is opened for; 全部 is one tab away and
    // is what find-in-page, printing and select-all-copy need.
    const requested = new URL(window.location.href).searchParams.get(SEMESTER_PARAM);
    select(semesters.includes(requested) ? requested : newestFirst[0]);
}

function renderCharts(analysis, semesters) {
    new Chart(document.getElementById('gpaChart'), {
        type: 'line',
        data: {
            labels: semesters,
            datasets: [{
                label: '平均 GPA',
                data: analysis.per_semester.map((s) => s.gpa),
                borderColor: '#4f46e5', backgroundColor: 'rgba(79,70,229,0.1)',
                tension: 0.3, spanGaps: true, fill: true
            }]
        },
        options: {responsive: true, scales: {y: {suggestedMin: 2.0, suggestedMax: 4.3}}}
    });

    new Chart(document.getElementById('creditChart'), {
        type: 'bar',
        data: {
            labels: semesters,
            datasets: [{
                label: '修習學分',
                data: analysis.per_semester.map((s) => s.attempted_credits),
                backgroundColor: 'rgba(16,185,129,0.6)', borderColor: 'rgba(16,185,129,1)', borderWidth: 1
            }]
        },
        options: {responsive: true, scales: {y: {beginAtZero: true}}}
    });

    const datasets = GRADE_ORDER.map((letter) => ({
        label: letter,
        data: analysis.per_semester.map((s) => (s.grade_credits || {})[letter] || 0),
        backgroundColor: color(letter, 0.8),
        borderColor: color(letter, 1),
        borderWidth: 1
    })).reverse();

    new Chart(document.getElementById('stackedChart'), {
        type: 'bar',
        data: {labels: semesters, datasets},
        options: {responsive: true, scales: {x: {stacked: true}, y: {stacked: true, beginAtZero: true}}}
    });
}

function showError(message, detail) {
    const loading = document.getElementById('loading');
    // loadData() hides #loading before it renders, so anything throwing from the
    // render calls would otherwise leave a blank dashboard and no message at all.
    loading.classList.remove('hidden');
    document.getElementById('content').classList.add('hidden');
    loading.replaceChildren();
    const title = document.createElement('p');
    title.className = 'text-red-600';
    title.textContent = message;
    loading.appendChild(title);
    if (detail) {
        const sub = document.createElement('p');
        sub.className = 'text-sm text-gray-500 mt-2';
        sub.textContent = detail;
        loading.appendChild(sub);
    }
}

async function loadData() {
    const res = await fetch('/api/grade-data');

    if (!res.ok) {
        let detail = '';
        if (res.headers.get('content-type')?.includes('json')) {
            detail = (await res.json().catch(() => ({}))).detail || '';
        }
        showError(`抓取資料失敗 (${res.status})`, detail);
        if (res.status === 401) setTimeout(() => location.assign('/login'), 2000);
        return;
    }

    const data = await res.json();
    const analysis = data.analysis;

    document.getElementById('loading').classList.add('hidden');
    const contentEl = document.getElementById('content');
    contentEl.classList.remove('hidden');
    contentEl.classList.add('fade-in');

    renderStudentInfo(data.student_info);

    document.getElementById('overallGpa').textContent = fmtGpa(analysis.overall.gpa);
    const latest = analysis.per_semester.at(-1);
    document.getElementById('latestGpa').textContent = latest ? fmtGpa(latest.gpa) : '—';

    renderCreditsSummary(data.credits_summary);
    renderRankings(data.rankings);
    renderCharts(analysis, data.semesters);
    renderLegend('legendPopoverBody', analysis.grade_map);
    renderCourses(data.courses, data.semesters);

    document.getElementById('fetchTime').textContent =
        `資料擷取時間：${new Date().toLocaleString('zh-TW', {hour12: false})}`;
}

// Guarded so the unit tests can require this file; neither global exists in the other.
if (typeof document !== 'undefined') {
    loadData().catch((err) => {
        console.error(err);
        showError('載入資料時發生錯誤，請稍後再試或回報問題。');
    });
}

if (typeof module !== 'undefined') module.exports = {esc, fmtGpa, semesterOf, orderCourses};
