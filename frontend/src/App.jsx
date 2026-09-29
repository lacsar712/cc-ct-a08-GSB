import { createSignal, onMount, Show, For, createEffect } from "solid-js";
import {
  clearSession,
  createSubmission,
  fetchBanRejections,
  fetchBanWindow,
  fetchSubmission,
  fetchSubmissions,
  getUser,
  login,
  setSession,
  updateBanWindow,
} from "./api";

const statusLabel = {
  pending: "待复核",
  processing: "复核中",
  done: "已完成",
};

const roleLabel = {
  machinist: "操作员",
  auditor: "复核员",
};

function readHash() {
  const raw = (location.hash || "#/").replace(/^#/, "") || "/";
  const m = raw.match(/^\/detail\/(\d+)/);
  if (m) return { name: "detail", id: Number(m[1]) };
  if (raw === "/ban") return { name: "ban", id: null };
  return { name: "home", id: null };
}

function toHM(t) {
  // 服务端返回 "HH:MM:SS"，<input type="time"> 用 HH:MM
  return t ? t.slice(0, 5) : "";
}

function App() {
  const [user, setUser] = createSignal(getUser());
  const [rows, setRows] = createSignal([]);
  const [detail, setDetail] = createSignal(null);
  const [route, setRoute] = createSignal(readHash());
  const [error, setError] = createSignal("");
  const [notice, setNotice] = createSignal("");
  const [loading, setLoading] = createSignal(false);

  const [loginUser, setLoginUser] = createSignal("machinist");
  const [loginPass, setLoginPass] = createSignal("machine123456");

  const [toolCode, setToolCode] = createSignal("");
  const [offsetUm, setOffsetUm] = createSignal("");

  // 禁交台状态：一切以后台返回为准，不看前端本地钟点
  const [banWindow, setBanWindow] = createSignal(null);
  const [rejections, setRejections] = createSignal([]);
  const [banStart, setBanStart] = createSignal("00:00");
  const [banEnd, setBanEnd] = createSignal("00:00");
  const [banLoading, setBanLoading] = createSignal(false);
  const [banSaving, setBanSaving] = createSignal(false);

  function goHome() {
    location.hash = "#/";
  }

  function goDetail(id) {
    location.hash = `#/detail/${id}`;
  }

  function goBan() {
    location.hash = "#/ban";
  }

  async function loadRows() {
    setLoading(true);
    setError("");
    try {
      const data = await fetchSubmissions();
      setRows(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function loadDetail(id) {
    setLoading(true);
    setError("");
    try {
      setDetail(await fetchSubmission(id));
    } catch (e) {
      setError(e.message);
      setDetail(null);
    } finally {
      setLoading(false);
    }
  }

  function applyWindow(data) {
    setBanWindow(data);
    if (data.configured) {
      setBanStart(toHM(data.start_time));
      setBanEnd(toHM(data.end_time));
    }
  }

  async function loadBanWindow() {
    try {
      applyWindow(await fetchBanWindow());
    } catch (e) {
      // 状态条不应因一次拉取失败就谎称可交：清空并提示
      setBanWindow(null);
      setError(e.message);
    }
  }

  async function loadRejections() {
    try {
      setRejections(await fetchBanRejections());
    } catch (e) {
      setError(e.message);
    }
  }

  async function loadBan() {
    setBanLoading(true);
    setError("");
    await Promise.all([loadBanWindow(), loadRejections()]);
    setBanLoading(false);
  }

  onMount(() => {
    const onHash = () => setRoute(readHash());
    window.addEventListener("hashchange", onHash);
    if (user()) {
      if (route().name === "detail") loadDetail(route().id);
      else if (route().name === "ban") loadBan();
      else {
        loadRows();
        loadBanWindow();
      }
    }
    return () => window.removeEventListener("hashchange", onHash);
  });

  createEffect(() => {
    const r = route();
    if (!user()) return;
    if (r.name === "detail" && r.id) loadDetail(r.id);
    else if (r.name === "ban") loadBan();
    else {
      loadRows();
      loadBanWindow();
    }
  });

  async function handleLogin(e) {
    e.preventDefault();
    setError("");
    try {
      const data = await login(loginUser(), loginPass());
      setSession(data.token, {
        username: data.username,
        role: data.role,
        can_write: data.can_write,
      });
      setUser(getUser());
      goHome();
      await loadRows();
      await loadBanWindow();
    } catch (err) {
      setError(err.message);
    }
  }

  function handleLogout() {
    clearSession();
    setUser(null);
    setRows([]);
    setDetail(null);
    setBanWindow(null);
    setRejections([]);
    goHome();
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setNotice("");
    try {
      await createSubmission(toolCode(), offsetUm());
      setToolCode("");
      setOffsetUm("");
      setNotice("刀补已提交，等待复核。");
      await loadRows();
    } catch (err) {
      // 后台才是最终裁决；被挡后立即以服务器状态刷新徽章，绝不只改提示放过写接口
      setError(err.message);
    } finally {
      await loadBanWindow();
    }
  }

  async function handleSaveBan(e) {
    e.preventDefault();
    setError("");
    setNotice("");
    if (!banStart() || !banEnd()) {
      setError("请填写每日禁交起止钟点");
      return;
    }
    setBanSaving(true);
    try {
      const data = await updateBanWindow(banStart(), banEnd());
      applyWindow(data);
      await loadRejections();
      setNotice(
        data.start_time === data.end_time || banStart() === banEnd()
          ? "禁交钟点已保存并立即生效：起止相同，全天禁交。"
          : "禁交钟点已保存并立即生效（起晚于止视为跨夜，含起止钟点）。"
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setBanSaving(false);
    }
  }

  function BanBadge(props) {
    const w = () => props.window;
    return (
      <Show
        when={w()}
        fallback={<span class="badge badge-unknown">禁交状态读取中…（以后台为准）</span>}
      >
        <span class={w().is_banned_now ? "badge badge-ban" : "badge badge-ok"}>
          {w().is_banned_now ? "此刻禁交" : "此刻可交"}
        </span>
        <span class="hint">
          服务器时刻 {new Date(w().server_time).toLocaleString()}
          {w().configured
            ? `｜每日禁交 ${toHM(w().start_time)}–${toHM(w().end_time)}（含起止钟点）`
            : "｜尚未设置禁交钟点"}
        </span>
      </Show>
    );
  }

  return (
    <div class="page">
      <header class="topbar">
        <div class="brand">
          <h1>数控刀补复核台</h1>
          <p class="hint">刀补绝对值不超过十二微米判合格，否则超差。夜班禁交时段由后台按服务器钟点闭区间挡回。</p>
        </div>
        <Show when={user()}>
          <nav class="topnav">
            <a
              href="#/"
              class={route().name === "home" ? "active" : ""}
              onClick={(e) => {
                e.preventDefault();
                goHome();
              }}
            >
              复核总览
            </a>
            <a
              href="#/ban"
              class={route().name === "ban" ? "active" : ""}
              onClick={(e) => {
                e.preventDefault();
                goBan();
              }}
            >
              禁交台
            </a>
          </nav>
        </Show>
      </header>

      <Show when={error()}>
        <div class="banner error">{error()}</div>
      </Show>
      <Show when={notice()}>
        <div class="banner ok">{notice()}</div>
      </Show>

      <Show
        when={user()}
        fallback={
          <section class="card">
            <h2>登录</h2>
            <form onSubmit={handleLogin} class="form">
              <label>
                用户名
                <input
                  value={loginUser()}
                  onInput={(e) => setLoginUser(e.currentTarget.value)}
                />
              </label>
              <label>
                密码
                <input
                  type="password"
                  value={loginPass()}
                  onInput={(e) => setLoginPass(e.currentTarget.value)}
                />
              </label>
              <button type="submit">进入系统</button>
            </form>
            <p class="hint">操作员 machinist / machine123456；复核员 auditor / audit123456（只读）</p>
          </section>
        }
      >
        <section class="card toolbar">
          <div>
            当前用户：<strong>{user().username}</strong>（{roleLabel[user().role] || user().role}）
          </div>
          <button type="button" class="ghost" onClick={handleLogout}>
            退出
          </button>
        </section>

        <Show when={route().name === "home"}>
          <section class="card">
            <div class="toolbar">
              <h2>此刻是否禁交</h2>
              <button type="button" class="ghost" onClick={loadBanWindow}>
                刷新服务器状态
              </button>
            </div>
            <p class="status-line">
              <BanBadge window={banWindow()} />
            </p>
            <p class="hint">能否交刀补一律由后台按服务器时刻裁决，本机改钟点无效。</p>
          </section>

          <Show when={user().can_write}>
            <section class="card">
              <h2>提交刀补</h2>
              <form onSubmit={handleSubmit} class="form inline">
                <label>
                  刀具编号
                  <input
                    placeholder="如 T01"
                    value={toolCode()}
                    onInput={(e) => setToolCode(e.currentTarget.value)}
                    required
                  />
                </label>
                <label>
                  刀补（微米）
                  <input
                    type="number"
                    value={offsetUm()}
                    onInput={(e) => setOffsetUm(e.currentTarget.value)}
                    required
                  />
                </label>
                <button type="submit">提交待复核</button>
              </form>
            </section>
          </Show>

          <section class="card">
            <div class="toolbar">
              <h2>复核列表</h2>
              <button type="button" class="ghost" onClick={loadRows} disabled={loading()}>
                {loading() ? "刷新中…" : "刷新"}
              </button>
            </div>
            <table>
              <thead>
                <tr>
                  <th>刀具</th>
                  <th>刀补 µm</th>
                  <th>状态</th>
                  <th>结论</th>
                  <th>提交时间</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                <For each={rows()}>
                  {(row) => (
                    <tr>
                      <td>{row.tool_code}</td>
                      <td>{row.offset_um}</td>
                      <td>{statusLabel[row.status] || row.status}</td>
                      <td class={row.verdict === "合格" ? "pass" : row.verdict === "超差" ? "fail" : ""}>
                        {row.verdict || "—"}
                      </td>
                      <td>{new Date(row.created_at).toLocaleString()}</td>
                      <td>
                        <button type="button" class="ghost" onClick={() => goDetail(row.id)}>
                          详情
                        </button>
                      </td>
                    </tr>
                  )}
                </For>
              </tbody>
            </table>
            <Show when={!rows().length && !loading()}>
              <p class="hint">暂无记录</p>
            </Show>
          </section>
        </Show>

        <Show when={route().name === "ban"}>
          <section class="card">
            <div class="toolbar">
              <h2>禁交台 · 此刻是否禁交</h2>
              <button type="button" class="ghost" onClick={loadBan} disabled={banLoading()}>
                {banLoading() ? "刷新中…" : "刷新"}
              </button>
            </div>
            <p class="status-line">
              <BanBadge window={banWindow()} />
            </p>
          </section>

          <section class="card">
            <h2>禁交钟点设置</h2>
            <Show
              when={user().can_write}
              fallback={
                <div>
                  <p class="hint">
                    当前为只读账号，禁交钟点如下，不可修改：
                  </p>
                  <p>
                    每日禁交：
                    <strong>
                      <Show when={banWindow()?.configured} fallback={"尚未设置"}>
                        {toHM(banWindow().start_time)}–{toHM(banWindow().end_time)}
                      </Show>
                    </strong>
                    （闭区间，含起止钟点）
                  </p>
                </div>
              }
            >
              <form onSubmit={handleSaveBan} class="form inline">
                <label>
                  每日禁交起
                  <input
                    type="time"
                    value={banStart()}
                    onInput={(e) => setBanStart(e.currentTarget.value)}
                    required
                  />
                </label>
                <label>
                  每日禁交止
                  <input
                    type="time"
                    value={banEnd()}
                    onInput={(e) => setBanEnd(e.currentTarget.value)}
                    required
                  />
                </label>
                <button type="submit" disabled={banSaving()}>
                  {banSaving() ? "保存中…" : "保存并立即生效"}
                </button>
              </form>
              <p class="hint">
                起钟点晚于止钟点视为跨夜（夜班）；起止相同视为全天禁交。判定与计时均在后台按服务器时刻执行。
              </p>
            </Show>
          </section>

          <section class="card">
            <h2>禁交流水（挡回记录）</h2>
            <table>
              <thead>
                <tr>
                  <th>服务器判定时刻</th>
                  <th>刀具</th>
                  <th>刀补 µm</th>
                  <th>命中禁交时段</th>
                  <th>操作人</th>
                </tr>
              </thead>
              <tbody>
                <For each={rejections()}>
                  {(r) => (
                    <tr>
                      <td>{new Date(r.server_time).toLocaleString()}</td>
                      <td>{r.tool_code}</td>
                      <td>{r.offset_um}</td>
                      <td>
                        {toHM(r.start_time)}–{toHM(r.end_time)}
                      </td>
                      <td>{r.rejected_by || "—"}</td>
                    </tr>
                  )}
                </For>
              </tbody>
            </table>
            <Show when={!rejections().length && !banLoading()}>
              <p class="hint">暂无挡回流水</p>
            </Show>
          </section>
        </Show>

        <Show when={route().name === "detail"}>
          <section class="card">
            <div class="toolbar">
              <h2>刀补详情</h2>
              <button type="button" class="ghost" onClick={goHome}>
                返回总览
              </button>
            </div>
            <Show when={detail()} fallback={<p class="hint">{loading() ? "加载中…" : "未找到记录"}</p>}>
              {(d) => (
                <div class="detail-grid">
                  <p>编号：{d().id}</p>
                  <p>刀具：{d().tool_code}</p>
                  <p>刀补 µm：{d().offset_um}</p>
                  <p>状态：{statusLabel[d().status] || d().status}</p>
                  <p class={d().verdict === "合格" ? "pass" : d().verdict === "超差" ? "fail" : ""}>
                    结论：{d().verdict || "—"}
                  </p>
                  <p>提交时间：{new Date(d().created_at).toLocaleString()}</p>
                  <p>
                    复核时间：
                    {d().reviewed_at ? new Date(d().reviewed_at).toLocaleString() : "—"}
                  </p>
                </div>
              )}
            </Show>
          </section>
        </Show>
      </Show>
    </div>
  );
}

export default App;
