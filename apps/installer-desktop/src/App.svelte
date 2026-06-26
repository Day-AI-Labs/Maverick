<script lang="ts">
  import { invoke } from '@tauri-apps/api/core';
  import { listen, type UnlistenFn } from '@tauri-apps/api/event';
  import { onMount, onDestroy } from 'svelte';

  type Status = 'idle' | 'installing' | 'done' | 'failed';

  let status: Status = 'idle';
  let lines: string[] = [];
  let errorMsg = '';
  let logEl: HTMLElement | undefined;

  const unlisteners: UnlistenFn[] = [];

  onMount(async () => {
    unlisteners.push(
      await listen<string>('install-log', (e) => {
        lines = [...lines, e.payload];
        // autoscroll to the newest line
        queueMicrotask(() => logEl?.scrollTo(0, logEl.scrollHeight));
      })
    );
    unlisteners.push(await listen('install-done', () => { status = 'done'; }));
    unlisteners.push(
      await listen<string>('install-failed', (e) => {
        status = 'failed';
        errorMsg = e.payload;
      })
    );
  });

  onDestroy(() => unlisteners.forEach((f) => f()));

  async function startInstall() {
    status = 'installing';
    lines = [];
    errorMsg = '';
    try {
      await invoke('install');
    } catch (e) {
      // Failure is normally delivered via the install-failed event (which
      // may have already run during the await and set status='failed' with
      // a specific errorMsg); only fall back to the generic message if it
      // hasn't. Cast through Status because TS flow-narrows `status` to
      // 'installing' here and can't see the event listener's mutation.
      if ((status as Status) !== 'failed') {
        status = 'failed';
        errorMsg = String(e);
      }
    }
  }
</script>

<main>
  <header>
    <h1>Lightwork</h1>
    <p class="sub">Install the Lightwork agent on this machine.</p>
  </header>

  {#if status === 'idle'}
    <section>
      <p>
        This installs Python (if it isn't already) and Lightwork, then you'll run a
        quick one-time setup. It takes a couple of minutes.
      </p>
      <button on:click={startInstall}>Install Lightwork</button>
    </section>
  {:else if status === 'installing'}
    <section>
      <h2>Installing…</h2>
      <p class="sub">Hang tight — this can take a minute or two.</p>
      <pre bind:this={logEl} class="log">{lines.join('\n')}</pre>
    </section>
  {:else if status === 'done'}
    <section class="done">
      <h2>Lightwork is installed. 🎉</h2>
      <p>Open a terminal and run <code>maverick init</code> to finish setup.</p>
      <pre class="log">{lines.join('\n')}</pre>
    </section>
  {:else}
    <section class="failed">
      <h2>Install failed</h2>
      <p class="error">{errorMsg}</p>
      <pre class="log">{lines.join('\n')}</pre>
      <button on:click={startInstall}>Try again</button>
    </section>
  {/if}
</main>

<style>
  :global(body) {
    margin: 0;
    font-family: -apple-system, system-ui, sans-serif;
    background: #0d1117;
    color: #f0f6fc;
  }
  main { padding: 2rem; max-width: 720px; margin: 0 auto; }
  header { margin-bottom: 2rem; }
  h1 { font-size: 2rem; margin: 0; }
  .sub { color: #8b949e; }
  section { background: #161b22; padding: 1.5rem; border-radius: 8px; }
  h2 { margin-top: 0; font-size: 1.25rem; }
  button {
    background: #238636; color: #fff; border: none; padding: 0.7rem 1.2rem;
    border-radius: 6px; cursor: pointer; font-size: 1rem;
  }
  button:hover { background: #2ea043; }
  code {
    background: #0d1117; border: 1px solid #30363d; border-radius: 4px;
    padding: 0.1rem 0.35rem; font-size: 0.9em;
  }
  .log {
    margin-top: 1rem; max-height: 320px; overflow: auto;
    background: #010409; border: 1px solid #30363d; border-radius: 6px;
    padding: 0.75rem; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.8rem; line-height: 1.4; white-space: pre-wrap; word-break: break-word;
    color: #c9d1d9;
  }
  .done h2 { color: #2ea043; }
  .failed h2 { color: #f85149; }
  .error { color: #f85149; }
</style>
