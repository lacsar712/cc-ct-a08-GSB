import { createSignal, onMount, Show, For } from "solid-js";
import {
  fetchCurfewSettings,
  fetchCurfewStatus,
  fetchRejections,
  updateCurfewSettings,
} from "./api";

function CurfewDesk(props) {
  const [settings, setSettings] = createSignal(null);
  const [status, setStatus] = createSignal(null);
  const [logs, setLogs] = createSignal([]);
  const [startInput, setStartInput] = createSignal("22:00");
  const [endInput, setEndInput] = createSignal("06:00");
  const [enabledInput, setEnabledInput] = createSignal(true);
  const [loading, setLoading] = createSignal(false);
  const [saving, setSaving] = createSignal(false);
  const [error, setError] = createSignal("");
  const [notice, setNotice] = createSignal("");

  async function loadAll() {
    setLoading(true);
    setError("");
    try {
      const [s, st, lg] = await Promise.all([
        fetchCurfewSettings(),
        fetchCurfewStatus(),
        fetchRejections(),
      ]);
      setSettings(s);
      setStartInput(s.start_time);
      setEndInput(s.end_time);
      setEnabledInput(s.enabled);
      setStatus(st);
      setLogs(lg);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  onMount(loadAll);

  async function handleSave(e) {
    e.preventDefault();
    setError("");
    setNotice("");
    setSaving(true);
    try {
      const saved = await updateCurfewSettings({
        start_time: startInput(),
        end_time: endInput(),
        enabled: enabledInput(),
      });
      setSettings(saved);
      setNotice("禁交钟点已更新，下一次提交立即按新钟点判定（服务器时刻）。");
      // 改完立即刷新此刻状态与流水
      const [st, lg] = await Promise.all([fetchCurfewStatus(), fetchRejections()]);
      setStatus(st);
      setLogs(lg);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  const canWrite = () => props.user?.can_write;

  return (
    <section class="card">
      <div class="toolbar">
        <h2>禁交台</h2>
        <button type="button" class="ghost" onClick={loadAll} disabled={loading()}>
          {loading() ? "刷新中…" : "刷新"}
        </button>
      </div>
      <p class="hint">
        夜班关闭交刀补通道。是否禁交一律以<strong>服务器时刻</strong>判定，落在起止钟点构成的闭区间内即挡回；
        前端本机钟点不参与判定。挡回的每次尝试都会在同一事务内追加一条禁交流水。
      </p>

      <Show when={error()}>
        <div class="banner error">{error()}</div>
      </Show>
      <Show when={notice()}>
        <div class="banner ok">{notice()}</div>
      </Show>

      {/* 块一：钟点设置 */}
      <div class="curfew-block">
        <h3>禁交钟点设置</h3>
        <Show when={settings()} fallback={<p class="hint">加载中…</p>}>
          {(s) => (
            <Show
              when={canWrite()}
              fallback={
                <div class="readonly-box">
                  <p>
                    禁交起止：<strong>{s().start_time} – {s().end_time}</strong>
                    （{s().enabled ? "已启用" : "已停用"}）
                  </p>
                  <p class="hint">当前账号为只读员，可查看钟点，不能修改。</p>
                  <p class="hint">
                    最近修改：{s().updated_by ? s().updated_by : "—"}
                    {s().updated_at ? ` / ${new Date(s().updated_at).toLocaleString()}` : ""}
                  </p>
                </div>
              }
            >
              <form class="form inline" onSubmit={handleSave}>
                <label>
                  禁交开始
                  <input
                    type="time"
                    value={startInput()}
                    onInput={(e) => setStartInput(e.currentTarget.value)}
                    required
                  />
                </label>
                <label>
                  禁交结束
                  <input
                    type="time"
                    value={endInput()}
                    onInput={(e) => setEndInput(e.currentTarget.value)}
                    required
                  />
                </label>
                <label class="check">
                  <span>启用禁交</span>
                  <input
                    type="checkbox"
                    checked={enabledInput()}
                    onChange={(e) => setEnabledInput(e.currentTarget.checked)}
                  />
                </label>
                <button type="submit" disabled={saving()}>
                  {saving() ? "保存中…" : "保存并立即生效"}
                </button>
              </form>
              <p class="hint">
                开始晚于结束表示跨午夜（如 22:00–06:00）；起止相同视为全天禁交。
                最近修改：{s().updated_by ? s().updated_by : "—"}
                {s().updated_at ? ` / ${new Date(s().updated_at).toLocaleString()}` : ""}
              </p>
            </Show>
          )}
        </Show>
      </div>

      {/* 块二：此刻是否禁交（以后端 status 为准） */}
      <div class="curfew-block">
        <h3>此刻是否禁交</h3>
        <Show when={status()} fallback={<p class="hint">加载中…</p>}>
          {(st) => (
            <div class={`status-box ${st().blocked ? "blocked" : "open"}`}>
              <p class="status-word">
                {st().blocked ? "🚫 此刻正在禁交，交刀补会被挡回" : "✅ 此刻可交刀补"}
              </p>
              <p class="hint">
                服务器时刻：<strong>{st().server_clock}</strong>（以此为准，非本机钟点）
              </p>
              <p class="hint">
                禁交窗：{st().start_time} – {st().end_time}（闭区间，含起止钟点）·{" "}
                {st().enabled ? "已启用" : "已停用"}
              </p>
              <Show when={st().blocked}>
                <p class="hint">挡回原因：{st().reason}</p>
              </Show>
            </div>
          )}
        </Show>
      </div>

      {/* 块三：禁交流水 */}
      <div class="curfew-block">
        <h3>禁交流水</h3>
        <table>
          <thead>
            <tr>
              <th>服务器判定时刻</th>
              <th>刀具</th>
              <th>刀补 µm</th>
              <th>判定时窗口</th>
              <th>提交人</th>
              <th>挡回原因</th>
            </tr>
          </thead>
          <tbody>
            <For each={logs()}>
              {(row) => (
                <tr>
                  <td>{new Date(row.server_time).toLocaleString()}</td>
                  <td>{row.tool_code}</td>
                  <td>{row.offset_um}</td>
                  <td>{row.window_start} – {row.window_end}</td>
                  <td>{row.attempted_by || "—"}</td>
                  <td class="fail">{row.reason}</td>
                </tr>
              )}
            </For>
          </tbody>
        </table>
        <Show when={!logs().length && !loading()}>
          <p class="hint">暂无禁交流水</p>
        </Show>
      </div>
    </section>
  );
}

export default CurfewDesk;
