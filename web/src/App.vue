<script setup>
import { nextTick, onMounted, ref } from "vue";
import ChartBlock from "./ChartBlock.vue";

const messages = ref([]);
const input = ref("");
const loading = ref(false);
const provider = ref("");
const listEl = ref(null);

onMounted(async () => {
  try {
    const r = await fetch("/api/health");
    const b = await r.json();
    provider.value = b.provider || "";
  } catch {
    provider.value = "未连接";
  }
});

async function scrollBottom() {
  await nextTick();
  if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight;
}

async function send() {
  const q = input.value.trim();
  if (!q || loading.value) return;
  input.value = "";
  const assistant = { role: "assistant", pending: true, liveSteps: [] };
  messages.value.push({ role: "user", text: q }, assistant);
  loading.value = true;
  scrollBottom();
  try {
    const resp = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q }),
    });
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const frame = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const line = frame.split("\n").find((l) => l.startsWith("data: "));
        if (!line) continue;
        let ev;
        try { ev = JSON.parse(line.slice(6)); } catch { continue; }
        if (ev.type === "step") {
          assistant.liveSteps.push(ev);
          scrollBottom();
        } else if (ev.type === "result") {
          Object.assign(assistant, ev, { pending: false });
          scrollBottom();
        }
      }
    }
    assistant.pending = false;
  } catch {
    assistant.pending = false;
    if (!assistant.type) assistant.error = assistant.error || "网络错误：后端未启动？";
  } finally {
    loading.value = false;
    scrollBottom();
  }
}

function onKeydown(e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
}
</script>

<template>
  <div class="app">
    <header class="topbar">
      <div>
        <h1>ChatBI-X</h1>
        <p class="sub">自然语言问数据 · Text2SQL Agent（propose-verify）</p>
      </div>
      <span class="badge" :class="{ off: provider === '未连接' || provider === 'openai_compat' }">
        {{ provider === "mock" ? "离线演示模式" : provider === "openai_compat" ? "真实计费模式" : provider === "未连接" ? "后端未连接" : `模型: ${provider}` }}
      </span>
    </header>

    <main class="list" ref="listEl">
      <div v-if="messages.length === 0" class="empty">
        <p>用自然语言提问，Agent 会生成并验证 SQL 后返回结果。</p>
        <p class="hint">试试：「每个城市的用户数量是多少？」「每个商品类别的销售额是多少？」</p>
      </div>

      <template v-for="(m, i) in messages" :key="i">
        <div v-if="m.role === 'user'" class="row user">
          <div class="bubble">{{ m.text }}</div>
        </div>

        <div v-else-if="m.pending" class="row bot">
          <div class="card pending">
            <span class="pulse">思考中…</span>
            <div v-for="(s, si) in m.liveSteps" :key="si" class="step">
              <span class="tag" :class="{ bad: s.ok === false }">{{ s.action }}</span>
              <code>{{ s.detail }}</code>
            </div>
          </div>
        </div>

        <div v-else class="row bot">
          <div class="card">
            <p v-if="m.summary" class="summary">{{ m.summary }}</p>
            <p v-if="m.error" class="err">⚠ {{ m.error }}</p>
            <pre v-if="m.sql" class="sql">{{ m.sql }}</pre>
            <ChartBlock
              v-if="m.chart && m.chart.type !== 'table' && m.rows && m.rows.length"
              :chart="m.chart"
              :columns="m.columns"
              :rows="m.rows"
            />
            <div v-if="m.rows && m.rows.length" class="tblwrap">
              <table>
                <thead>
                  <tr><th v-for="c in m.columns" :key="c">{{ c }}</th></tr>
                </thead>
                <tbody>
                  <tr v-for="(row, ri) in m.rows" :key="ri">
                    <td v-for="(cell, ci) in row" :key="ci">{{ cell }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <details v-if="m.steps && m.steps.length" class="steps" open>
              <summary>执行过程（{{ m.steps.length }} 步 · {{ m.elapsed_ms }}ms）</summary>
              <div v-for="(s, si) in m.steps" :key="si" class="step">
                <span class="tag" :class="{ bad: s.ok === false }">{{ s.action }}</span>
                <code>{{ s.detail }}</code>
              </div>
            </details>
          </div>
        </div>
      </template>
    </main>

    <footer class="composer">
      <textarea
        v-model="input"
        rows="1"
        placeholder="输入问题，Enter 发送，Shift+Enter 换行"
        @keydown="onKeydown"
      ></textarea>
      <button :disabled="loading || !input.trim()" @click="send">发送</button>
    </footer>
  </div>
</template>

<style scoped>
.app { display: flex; flex-direction: column; height: 100vh; }

.topbar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 20px; background: var(--card); border-bottom: 1px solid var(--line);
}
.topbar h1 { margin: 0; font-size: 18px; }
.sub { margin: 2px 0 0; font-size: 12px; color: var(--muted); }
.badge {
  font-size: 12px; padding: 4px 10px; border-radius: 999px;
  background: #ecfdf5; color: var(--ok); border: 1px solid #a7f3d0;
}
.badge.off { background: #fef2f2; color: var(--err); border-color: #fecaca; }

.list { flex: 1; overflow-y: auto; padding: 20px; }
.empty { text-align: center; color: var(--muted); margin-top: 15vh; }
.empty .hint { font-size: 13px; }

.row { display: flex; margin-bottom: 14px; }
.row.user { justify-content: flex-end; }
.bubble {
  background: var(--accent); color: #fff; padding: 10px 14px;
  border-radius: 12px 12px 2px 12px; max-width: 70%;
}
.card {
  background: var(--card); border: 1px solid var(--line); border-radius: 10px;
  padding: 12px 14px; max-width: 85%; min-width: 320px;
}
.pending { color: var(--muted); }
.pulse { animation: pulse 1.2s ease-in-out infinite; }
@keyframes pulse { 50% { opacity: 0.4; } }
.summary { margin: 0 0 8px; font-weight: 600; }
.err { margin: 0 0 8px; color: var(--err); font-size: 13px; }

.sql {
  background: #0f172a; color: #e2e8f0; padding: 10px 12px; border-radius: 8px;
  font-family: var(--mono); font-size: 12.5px; overflow-x: auto; margin: 0 0 10px;
}

.tblwrap { overflow: auto; max-height: 260px; border: 1px solid var(--line); border-radius: 8px; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { padding: 6px 12px; border-bottom: 1px solid var(--line); text-align: left; white-space: nowrap; }
th { background: #f9fafb; position: sticky; top: 0; }
tr:last-child td { border-bottom: none; }

.steps { margin-top: 10px; font-size: 12px; color: var(--muted); }
.steps summary { cursor: pointer; }
.step { display: flex; gap: 8px; align-items: baseline; margin-top: 6px; }
.step code { font-family: var(--mono); font-size: 11.5px; word-break: break-all; }
.tag {
  flex-shrink: 0; padding: 1px 8px; border-radius: 999px;
  background: #eff6ff; color: var(--accent); font-size: 11px;
}
.tag.bad { background: #fef2f2; color: var(--err); }

.composer {
  display: flex; gap: 10px; padding: 14px 20px;
  background: var(--card); border-top: 1px solid var(--line);
}
.composer textarea {
  flex: 1; resize: none; border: 1px solid var(--line); border-radius: 10px;
  padding: 10px 12px; font: inherit; outline: none;
}
.composer textarea:focus { border-color: var(--accent); }
.composer button {
  border: none; background: var(--accent); color: #fff; border-radius: 10px;
  padding: 0 22px; font-size: 14px; cursor: pointer;
}
.composer button:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
