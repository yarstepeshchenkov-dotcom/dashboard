/* ==========================================================================
   LITHIUM Intelligence Dashboard — клиентская логика
   ========================================================================== */

const POLL_INTERVAL_MS = 30000; // как часто проверять новые данные для уведомлений
const NOTIF_LIFETIME_MS = 8000; // сколько показывать всплывающее уведомление

let trendsChart = null;
let currentSentimentFilter = "all";

/* ---------------------------------------------------------------- УТИЛИТЫ */

async function apiGet(path) {
    const res = await fetch(path, { credentials: "same-origin" });
    if (res.status === 401) {
        window.location.href = "/";
        return null;
    }
    if (!res.ok) throw new Error(`${path} → ${res.status}`);
    return res.json();
}

async function apiPost(path) {
    const res = await fetch(path, { method: "POST", credentials: "same-origin" });
    if (res.status === 401) {
        window.location.href = "/";
        return null;
    }
    return res.json();
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str ?? "";
    return div.innerHTML;
}

function formatDate(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function sentimentBadge(sentiment) {
    const map = {
        positive: ["badge--positive", "Позитив"],
        negative: ["badge--negative", "Негатив"],
        neutral: ["badge--neutral", "Нейтрально"],
    };
    const [cls, label] = map[sentiment] || map.neutral;
    return `<span class="badge ${cls}">${label}</span>`;
}

/* ---------------------------------------------------------------- УВЕДОМЛЕНИЯ */

function showToast(title, text) {
    const stack = document.getElementById("notif-stack");
    const toast = document.createElement("div");
    toast.className = "notif-toast";
    toast.innerHTML = `<strong>${escapeHtml(title)}</strong>${escapeHtml(text)}`;
    stack.appendChild(toast);

    setTimeout(() => {
        toast.classList.add("leaving");
        setTimeout(() => toast.remove(), 320);
    }, NOTIF_LIFETIME_MS);
}

function getLastSeen(key) {
    return localStorage.getItem(key) || "";
}

function setLastSeen(key, value) {
    localStorage.setItem(key, value);
}

/* ---------------------------------------------------------------- ТАБЫ */

function initTabs() {
    document.querySelectorAll(".tab").forEach((btn) => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
            document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
            btn.classList.add("active");
            document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
        });
    });

    document.querySelectorAll(".filter-tab").forEach((btn) => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".filter-tab").forEach((b) => b.classList.remove("active"));
            btn.classList.add("active");
            currentSentimentFilter = btn.dataset.sentiment;
            loadMentions();
        });
    });
}

/* ---------------------------------------------------------------- СТАТУС САЙТА */

async function loadSiteStatus() {
    const dot = document.getElementById("status-dot");
    const label = document.getElementById("status-label");
    try {
        const data = await apiGet("/api/site-status");
        if (!data) return;
        if (data.up) {
            dot.className = "status-dot status-dot--up";
            label.textContent = "Сайт работает";
        } else {
            dot.className = "status-dot status-dot--down";
            label.textContent = "Сайт недоступен";
        }
    } catch (e) {
        dot.className = "status-dot status-dot--down";
        label.textContent = "Ошибка проверки";
    }
}

/* ---------------------------------------------------------------- ОБЗОР / СТАТИСТИКА */

async function loadStats() {
    try {
        const data = await apiGet("/api/stats");
        if (!data) return;
        document.getElementById("stat-total").textContent = data.total ?? "—";
        document.getElementById("stat-positive").textContent = data.positive ?? "—";
        document.getElementById("stat-negative").textContent = data.negative ?? "—";
        document.getElementById("stat-ads").textContent = data.ads_count ?? "—";
    } catch (e) {
        console.error("loadStats failed", e);
    }
}

async function loadTrends() {
    try {
        const data = await apiGet("/api/trends");
        if (!data) return;
        const items = data.items || [];

        const listEl = document.getElementById("trend-list");
        const chartEmpty = document.getElementById("trends-chart-empty");
        const canvas = document.getElementById("trends-chart");

        if (items.length === 0) {
            listEl.innerHTML = `<li class="muted">Нет данных по трендам</li>`;
            chartEmpty.hidden = false;
            canvas.hidden = true;
            if (trendsChart) { trendsChart.destroy(); trendsChart = null; }
            return;
        }

        chartEmpty.hidden = true;
        canvas.hidden = false;

        listEl.innerHTML = items
            .map(
                (t) => `
            <li>
                <span class="trend-name">${escapeHtml(t.keyword)}</span>
                <span class="trend-growth">+${Number(t.growth_percent).toFixed(1)}%</span>
            </li>`
            )
            .join("");

        const ctx = canvas.getContext("2d");
        const labels = items.map((t) => t.keyword);
        const values = items.map((t) => t.growth_percent);

        if (trendsChart) trendsChart.destroy();
        trendsChart = new Chart(ctx, {
            type: "bar",
            data: {
                labels,
                datasets: [
                    {
                        label: "Рост, %",
                        data: values,
                        backgroundColor: "#b8860b",
                        borderRadius: 4,
                        maxBarThickness: 46,
                    },
                ],
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: {
                    x: { ticks: { color: "#8a8a8a" }, grid: { display: false } },
                    y: { ticks: { color: "#8a8a8a" }, grid: { color: "#2a2a2a" } },
                },
            },
        });
    } catch (e) {
        console.error("loadTrends failed", e);
    }
}

/* ---------------------------------------------------------------- УПОМИНАНИЯ */

async function loadMentions(silent = false) {
    const tbody = document.getElementById("mentions-tbody");
    try {
        const data = await apiGet(`/api/mentions?sentiment=${currentSentimentFilter}`);
        if (!data) return;
        const items = data.items || [];

        if (items.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="muted">Упоминаний не найдено</td></tr>`;
            return;
        }

        tbody.innerHTML = items
            .map(
                (m) => `
            <tr data-id="${m.id}">
                <td>${escapeHtml(m.source)}</td>
                <td class="text-col" title="${escapeHtml(m.text)}">${escapeHtml(m.text)}</td>
                <td>${sentimentBadge(m.sentiment)}</td>
                <td>${m.is_b2b ? "B2B" : "—"}</td>
                <td>${formatDate(m.created_at)}</td>
                <td>
                    <button class="link-btn" onclick="markViewed(${m.id}, this)" ${m.viewed ? "disabled" : ""}>
                        ${m.viewed ? "Просмотрено" : "Отметить"}
                    </button>
                </td>
            </tr>`
            )
            .join("");

        if (!silent) checkForNewNegative(items);
    } catch (e) {
        console.error("loadMentions failed", e);
        tbody.innerHTML = `<tr><td colspan="6" class="muted">Не удалось загрузить данные</td></tr>`;
    }
}

async function markViewed(id, btn) {
    btn.disabled = true;
    btn.textContent = "…";
    const res = await apiPost(`/api/mentions/${id}/viewed`);
    if (res && res.ok) {
        btn.textContent = "Просмотрено";
    } else {
        btn.disabled = false;
        btn.textContent = "Отметить";
    }
}

function checkForNewNegative(items) {
    const lastSeenId = parseInt(getLastSeen("lastMentionId") || "0", 10);
    const newNegative = items.filter((m) => m.sentiment === "negative" && m.id > lastSeenId);

    if (items.length > 0) {
        const maxId = Math.max(...items.map((m) => m.id));
        if (maxId > lastSeenId) setLastSeen("lastMentionId", String(maxId));
    }

    if (lastSeenId > 0 && newNegative.length > 0) {
        showToast(
            "Новые негативные упоминания",
            `Обнаружено новых: ${newNegative.length}. Проверьте вкладку «Упоминания».`
        );
    }
}

/* ---------------------------------------------------------------- РЕКЛАМА КОНКУРЕНТОВ */

async function loadAds(silent = false) {
    const tbody = document.getElementById("ads-tbody");
    try {
        const data = await apiGet("/api/ads");
        if (!data) return;
        const items = data.items || [];

        if (items.length === 0) {
            tbody.innerHTML = `<tr><td colspan="4" class="muted">Реклама конкурентов не найдена</td></tr>`;
            return;
        }

        tbody.innerHTML = items
            .map(
                (a) => `
            <tr>
                <td>${escapeHtml(a.competitor)}</td>
                <td class="text-col" title="${escapeHtml(a.title)}">${escapeHtml(a.title)}</td>
                <td>${escapeHtml(a.platform)}</td>
                <td>${formatDate(a.created_at)}</td>
            </tr>`
            )
            .join("");

        if (!silent) checkForNewAds(items);
    } catch (e) {
        console.error("loadAds failed", e);
        tbody.innerHTML = `<tr><td colspan="4" class="muted">Не удалось загрузить данные</td></tr>`;
    }
}

function checkForNewAds(items) {
    const lastSeenId = parseInt(getLastSeen("lastAdId") || "0", 10);
    const newAds = items.filter((a) => a.id > lastSeenId);

    if (items.length > 0) {
        const maxId = Math.max(...items.map((a) => a.id));
        if (maxId > lastSeenId) setLastSeen("lastAdId", String(maxId));
    }

    if (lastSeenId > 0 && newAds.length > 0) {
        showToast(
            "Новая реклама конкурентов",
            `Новых объявлений: ${newAds.length}. Проверьте вкладку «Реклама конкурентов».`
        );
    }
}

/* ---------------------------------------------------------------- ГЕО-АНАЛИЗ */

async function loadGeo() {
    const thead = document.getElementById("geo-thead");
    const tbody = document.getElementById("geo-tbody");
    try {
        const data = await apiGet("/api/geo");
        if (!data) return;
        const cities = data.cities || [];
        const rows = data.rows || [];

        thead.innerHTML = `<tr><th>Бренд</th>${cities.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}</tr>`;

        if (rows.length === 0) {
            tbody.innerHTML = `<tr><td colspan="${cities.length + 1}" class="muted">Гео-данные пока недоступны</td></tr>`;
            return;
        }

        tbody.innerHTML = rows
            .map((r) => {
                const cells = cities
                    .map((c) => `<td>${r.positions[c] ?? "—"}</td>`)
                    .join("");
                const brandCell = r.brand === "LITHIUM"
                    ? `<td><strong style="color: var(--gold-bright)">${escapeHtml(r.brand)}</strong></td>`
                    : `<td>${escapeHtml(r.brand)}</td>`;
                return `<tr>${brandCell}${cells}</tr>`;
            })
            .join("");
    } catch (e) {
        console.error("loadGeo failed", e);
        tbody.innerHTML = `<tr><td class="muted">Не удалось загрузить данные</td></tr>`;
    }
}

/* ---------------------------------------------------------------- ИНИЦИАЛИЗАЦИЯ */

function loadAll(silent = false) {
    loadSiteStatus();
    loadStats();
    loadTrends();
    loadMentions(silent);
    loadAds(silent);
    loadGeo();
}

document.addEventListener("DOMContentLoaded", () => {
    initTabs();
    loadAll(true); // при первой загрузке не показываем уведомления, только запоминаем состояние

    setInterval(() => {
        loadSiteStatus();
        loadMentions(false);
        loadAds(false);
    }, POLL_INTERVAL_MS);

    setInterval(loadStats, POLL_INTERVAL_MS);
});
