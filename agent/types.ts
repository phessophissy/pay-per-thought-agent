// ─────────────────────────────────────────────────────────────
// Pay-Per-Thought Agent — Shared Type Definitions
// ─────────────────────────────────────────────────────────────

// ─── Tool Types ──────────────────────────────────────────────
export type ToolType = "anthropic" | "tavily" | "blockchain_rpc" | "reasoning";

export interface ToolConfig {
    anthropic?: {
        model: string;
        max_tokens: number;
    };
    tavily?: {
        search_depth: "basic" | "advanced";
        max_results: number;
    };
    blockchain_rpc?: {
        chain_id: number;
        method: string;
        params: unknown[];
    };
}

// ─── Step Types ──────────────────────────────────────────────
export interface Step {
    id: string;
    index: number;
    description: string;
    tool: ToolType;
    tool_config: ToolConfig;
    estimated_cost_usd: number;
    depends_on: string[];
}

export interface StepResult {
    step_id: string;
    index: number;
    status: "completed" | "failed" | "skipped" | "payment_denied";
    tool: ToolType;
    output: unknown;
    actual_cost_usd: number;
    duration_ms: number;
    payment_tx_hash: string | null;
    error: string | null;
    sources: string[];
    timestamp: string;
}

// ─── Execution Plan ──────────────────────────────────────────
export interface ExecutionPlan {
    session_id: string;
    query: string;
    steps: Step[];
    step_count: number;
    total_estimated_cost: number;
    max_budget: number;
    created_at: string;
}

// ─── x402 Payment Types ─────────────────────────────────────
export interface PaymentAuthorization {
    step_id: string;
    amount_usd: number;
    authorized: boolean;
    tx_hash: string | null;
    error: string | null;
}

export interface BudgetStatus {
    session_id: string;
    total_locked: number;
    total_spent: number;
    remaining: number;
    steps_completed: number;
    steps_remaining: number;
}

// ─── Agent Response (Final Output Schema) ────────────────────
export type AgentStatus =
    | "planning"
    | "awaiting_payment"
    | "executing"
    | "completed"
    | "halted"
    | "error";

export interface AgentResponse {
    status: AgentStatus;
    session_id: string;
    query: string;
    current_step: string;
    estimated_remaining_budget: number;
    plan: ExecutionPlan | null;
    actions: StepResult[];
    results: SynthesisResult | null;
    sources: string[];
    notes: string;
    timestamp: string;
}

// ─── Synthesis Result ─────────────────────────────────────────
export interface SynthesisResult {
    answer: string;
    confidence: "high" | "medium" | "low";
    key_findings: KeyFinding[];
    assumptions: string[];
    limitations: string[];
    sources: SourceReference[];
    total_cost_usd: number;
    steps_executed: number;
    steps_total: number;
    was_halted: boolean;
}

export interface KeyFinding {
    claim: string;
    evidence: string;
    source: string;
    confidence: "high" | "medium" | "low";
}

export interface SourceReference {
    url: string;
    title: string;
    relevance: string;
    accessed_at: string;
}

// ─── Cost Table ──────────────────────────────────────────────
export const COST_PER_TOOL: Record<ToolType, number> = {
    anthropic: 0.08,       // ~$0.08 per Claude Opus call (est. avg)
    tavily: 0.01,          // ~$0.01 per search
    blockchain_rpc: 0.001, // ~$0.001 per RPC call
    reasoning: 0.05,       // ~$0.05 per internal reasoning step
};
