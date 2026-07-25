import CopyButton from "./copy-button";

const install = "curl -fsSL https://autoexp.dev/install.sh | bash";

const agents = [
  ["Codex", "$autoexp", "codex plugin marketplace add shreyashkar-ml/autoexp\ncodex plugin add autoexp@autoexp"],
  ["Claude Code", "/autoexp", "claude plugin marketplace add shreyashkar-ml/autoexp\nclaude plugin install autoexp@autoexp"],
  ["OpenCode", "/autoexp", "Installed automatically"],
  ["Pi", "/autoexp", "Installed automatically"],
];

const features = [
  ["Reproducible runs", "Pin source, inputs, commands, environment, and outputs for every attempt."],
  ["Immutable evidence", "Inspect artifacts, logs, reports, metrics, and diffs without losing the run that produced them."],
  ["Human review", "Open a local review surface, annotate results, and send structured feedback straight back to the agent."],
  ["Keep or revert", "Optimize a scalar objective with a frozen evaluator and an auditable autoresearch loop."],
  ["Repository native", "Your worktree stays the editable source of truth. Autoexp supplies the harness around it."],
  ["Local first", "The dashboard and experiment ledger run on your machine. No account or hosted control plane."],
];

export default function Home() {
  return (
    <>
      <header className="nav shell">
        <a className="brand" href="#" aria-label="Autoexp home">
          auto<span>exp</span>
        </a>
        <nav aria-label="Main navigation">
          <a href="#how">How it works</a>
          <a href="#features">Features</a>
          <a href="#agents">Agents</a>
          <a href="https://github.com/shreyashkar-ml/autoexp">GitHub ↗</a>
        </nav>
      </header>

      <main>
        <section className="hero shell">
          <div className="eyebrow"><i /> local-first · open source · agent native</div>
          <h1>Run the experiment.<br /><em>Keep the evidence.</em></h1>
          <p className="lead">
            Reproducible experimentation infrastructure for coding agents.
            Compare variants, steer autoresearch, and make decisions from results—not vibes.
          </p>
          <div className="install">
            <span className="prompt">$</span>
            <code>{install}</code>
            <CopyButton text={install} />
          </div>
          <div className="hero-links">
            <a className="primary" href="#agents">Install for your agent</a>
            <a href="https://github.com/shreyashkar-ml/autoexp">View on GitHub →</a>
          </div>
          <div className="trust">
            <span>✓ runs locally</span>
            <span>✓ no account</span>
            <span>✓ no runtime dependencies</span>
            <span>✓ MIT licensed</span>
          </div>
        </section>

        <section className="product shell" aria-label="Autoexp dashboard preview">
          <div className="window">
            <div className="windowbar">
              <span className="lights"><i /><i /><i /></span>
              <code>localhost:4318 · autoexp</code>
              <span className="live"><i /> experiment running</span>
            </div>
            <img src="/autoexp_demo.png" alt="Autoexp dashboard showing experiment runs, evidence, milestones, and reports" />
          </div>
        </section>

        <section id="how" className="section shell">
          <div className="section-head">
            <span className="kicker">01 / workflow</span>
            <h2>Your agent proposes.<br />Autoexp proves.</h2>
            <p>One harness around the work your coding agent already does.</p>
          </div>
          <div className="steps">
            <article><b>01</b><h3>Define the boundary</h3><p>Set the objective, editable source, inputs, command, and evaluator.</p></article>
            <article><b>02</b><h3>Run focused variants</h3><p>Your agent changes the repository and Autoexp executes each proposal reproducibly.</p></article>
            <article><b>03</b><h3>Seal the result</h3><p>Source, outputs, logs, metrics, artifacts, and lineage become immutable evidence.</p></article>
            <article><b>04</b><h3>Decide from evidence</h3><p>A metric or your review keeps, reverts, or redirects the next attempt.</p></article>
          </div>
        </section>

        <section id="features" className="section shell">
          <div className="section-head">
            <span className="kicker">02 / infrastructure</span>
            <h2>The harness around<br />autonomous work.</h2>
          </div>
          <div className="feature-grid">
            {features.map(([title, body], index) => (
              <article key={title}>
                <span>0{index + 1}</span>
                <h3>{title}</h3>
                <p>{body}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="split shell">
          <div>
            <span className="kicker">standard experiments</span>
            <h2>Compare variants without losing the trail.</h2>
            <p>Every run keeps its source snapshot, execution context, artifacts, reports, and diff. Review the full chain before choosing a winner.</p>
            <code>autoexp run --agent --title &quot;candidate&quot;</code>
          </div>
          <div className="window compact">
            <div className="windowbar"><code>experiment / evidence</code><span className="live done">✓ sealed</span></div>
            <img src="/autoexp_demo.png" alt="Standard experiment view in Autoexp" />
          </div>
        </section>

        <section className="split reverse shell">
          <div>
            <span className="kicker">autoresearch</span>
            <h2>Let the metric drive the loop.</h2>
            <p>Freeze the evaluator, choose a direction, and let the agent iterate. Each attempt is scored, kept or reverted, and recorded.</p>
            <code>autoexp research attempt &quot;hypothesis&quot;</code>
          </div>
          <div className="window compact">
            <div className="windowbar"><code>autoresearch / attempt ledger</code><span className="live"><i /> optimizing</span></div>
            <img src="/autoresearch_demo.png" alt="Autoexp autoresearch loop and scored attempt ledger" />
          </div>
        </section>

        <section id="agents" className="section shell">
          <div className="section-head">
            <span className="kicker">03 / integrations</span>
            <h2>Use the agent<br />you already use.</h2>
            <p>One workflow across Codex, Claude Code, OpenCode, and Pi.</p>
          </div>
          <div className="agent-grid">
            {agents.map(([name, command, setup]) => (
              <article key={name}>
                <div><span className="agent-dot" /><h3>{name}</h3></div>
                <code>{command} &lt;objective&gt;</code>
                <pre>{setup}</pre>
              </article>
            ))}
          </div>
        </section>

        <section className="cta shell">
          <span className="kicker">start experimenting</span>
          <h2>Your next agent change<br />deserves a result.</h2>
          <div className="install">
            <span className="prompt">$</span>
            <code>{install}</code>
            <CopyButton text={install} />
          </div>
          <p>Linux and macOS · requires Git and uv</p>
        </section>
      </main>

      <footer className="shell">
        <a className="brand" href="#">auto<span>exp</span></a>
        <p>Local autonomous experimentation.</p>
        <div>
          <a href="https://github.com/shreyashkar-ml/autoexp">GitHub</a>
          <a href="https://github.com/shreyashkar-ml/autoexp/blob/main/LICENSE">MIT License</a>
        </div>
      </footer>
    </>
  );
}
