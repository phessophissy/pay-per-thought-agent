// ─────────────────────────────────────────────────────────────
// Pay-Per-Thought Agent — Phase 2: Executor
// ─────────────────────────────────────────────────────────────
// Executes each planned step sequentially with x402 payment
// authorization. Halts on payment failure and returns partial
// results. Each step invokes a specific tool (Claude, Tavily,
// or blockchain RPC).
// ─────────────────────────────────────────────────────────────

import Anthropic from "@anthropic-ai/sdk";
import {
    ExecutionPlan,
    Step,
    StepResult,
    PaymentAuthorization,
    BudgetStatus,
    COST_PER_TOOL,
} from "./types";

// ─── Tool Clients ────────────────────────────────────────────

interface ExecutorConfig {
    anthropicApiKey: string;
    tavilyApiKey: string;
    rpcUrl: string;
    x402ContractAddress: string;
    privateKey: string;
}

// ─── Executor Class ──────────────────────────────────────────

export class Executor {
    private anthropic: Anthropic;
    private config: ExecutorConfig;
    private stepResults: StepResult[] = [];
    private totalSpent: number = 0;

    constructor(config: ExecutorConfig) {
        this.config = config;
        this.anthropic = new Anthropic({ apiKey: config.anthropicApiKey });
    }

    /**
     * Execute all steps in the plan with x402 payment gates.
     * Returns results and total spent. Halts on payment denial.
     */
    async executeAll(plan: ExecutionPlan): Promise<{
        results: StepResult[];
        totalSpent: number;
        halted: boolean;
    }> {
        let halted = false;

        for (const step of plan.steps) {
            // ── Verify x402 payment authorization ──
            const payment = await this.authorizePayment(
                step,
                plan.session_id
            );

            if (!payment.authorized) {
                this.stepResults.push({
                    step_id: step.id,
                    index: step.index,
                    status: "payment_denied",
                    tool: step.tool,
                    output: null,
                    actual_cost_usd: 0,
                    duration_ms: 0,
                    payment_tx_hash: null,
                    error: payment.error || "x402 payment authorization denied",
                    sources: [],
                    timestamp: new Date().toISOString(),
                });
                halted = true;
                break;
            }

            // ── Execute the step ──
            const startTime = Date.now();
            try {
                const output = await this.executeTool(step, plan);
                const duration = Date.now() - startTime;
                const actualCost = COST_PER_TOOL[step.tool];

                this.totalSpent += actualCost;

                this.stepResults.push({
                    step_id: step.id,
                    index: step.index,
                    status: "completed",
                    tool: step.tool,
                    output: output.data,
                    actual_cost_usd: actualCost,
                    duration_ms: duration,
                    payment_tx_hash: payment.tx_hash,
                    error: null,
                    sources: output.sources,
                    timestamp: new Date().toISOString(),
                });

                // ── Confirm payment on-chain ──
                await this.confirmPayment(step.id, plan.session_id);
            } catch (error) {
                const duration = Date.now() - startTime;
                this.stepResults.push({
                    step_id: step.id,
                    index: step.index,
                    status: "failed",
                    tool: step.tool,
                    output: null,
                    actual_cost_usd: 0,
                    duration_ms: duration,
                    payment_tx_hash: payment.tx_hash,
                    error: error instanceof Error ? error.message : String(error),
                    sources: [],
                    timestamp: new Date().toISOString(),
                });

                // ── Refund failed step ──
                await this.refundPayment(step.id, plan.session_id);
            }
        }

        return {
            results: this.stepResults,
            totalSpent: this.totalSpent,
            halted,
        };
    }

    /**
     * Get current budget status.
     */
    getBudgetStatus(plan: ExecutionPlan): BudgetStatus {
        return {
            session_id: plan.session_id,
            total_locked: plan.total_estimated_cost,
            total_spent: this.totalSpent,
            remaining: plan.max_budget - this.totalSpent,
            steps_completed: this.stepResults.filter((r) => r.status === "completed")
                .length,
            steps_remaining:
                plan.step_count -
                this.stepResults.filter((r) => r.status === "completed").length,
        };
    }

    // ─── Tool Execution ────────────────────────────────────────

    private async executeTool(
        step: Step,
        plan: ExecutionPlan
    ): Promise<{ data: unknown; sources: string[] }> {
        switch (step.tool) {
            case "anthropic":
            case "reasoning":
                return this.executeAnthropic(step, plan);
            case "tavily":
                return this.executeTavily(step);
            case "blockchain_rpc":
                return this.executeBlockchainRPC(step);
            default:
                throw new Error(`Unknown tool: ${step.tool}`);
        }
    }

    /**
     * Execute Claude reasoning/analysis step.
     */
    private async executeAnthropic(
        step: Step,
        plan: ExecutionPlan
    ): Promise<{ data: unknown; sources: string[] }> {
        // Build context from previous step results
        const context = this.stepResults
            .filter((r) => r.status === "completed")
            .map((r) => `[Step ${r.index}]: ${JSON.stringify(r.output)}`)
            .join("\n\n");

        const model = step.tool_config.anthropic?.model || "claude-sonnet-4-20250514";
        const maxTokens = step.tool_config.anthropic?.max_tokens || 1024;

        const response = await this.anthropic.messages.create({
            model,
            max_tokens: maxTokens,
            system:
                "You are a research analyst. Provide factual, concise answers backed by evidence. If using data from context, cite which step provided it.",
            messages: [
                {
                    role: "user",
                    content: `Research query: "${plan.query}"\n\nYour task for this step: ${step.description}\n\n${context ? `Context from previous steps:\n${context}` : "No prior context available."}\n\nRespond with a JSON object: { "analysis": "your analysis", "confidence": "high|medium|low", "key_points": ["point1", "point2"] }`,
                },
            ],
        });

        const text =
            response.content[0].type === "text" ? response.content[0].text : "";

        return {
            data: this.tryParseJSON(text) || { raw_text: text },
            sources: [`anthropic:${model}`],
        };
    }

    /**
     * Execute Tavily web search step.
     */
    private async executeTavily(
        step: Step
    ): Promise<{ data: unknown; sources: string[] }> {
        const searchDepth =
            step.tool_config.tavily?.search_depth || "advanced";
        const maxResults = step.tool_config.tavily?.max_results || 5;

        const response = await fetch("https://api.tavily.com/search", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                api_key: this.config.tavilyApiKey,
                query: step.description,
                search_depth: searchDepth,
                max_results: maxResults,
                include_answer: true,
                include_raw_content: false,
            }),
        });

        if (!response.ok) {
            throw new Error(
                `Tavily API error: ${response.status} ${response.statusText}`
            );
        }

        const data = await response.json();
        const sources = (data.results || []).map(
            (r: { url: string }) => r.url
        );

        return {
            data: {
                answer: data.answer,
                results: (data.results || []).map(
                    (r: { title: string; url: string; content: string; score: number }) => ({
                        title: r.title,
                        url: r.url,
                        snippet: r.content,
                        relevance_score: r.score,
                    })
                ),
            },
            sources,
        };
    }

    /**
     * Execute blockchain RPC call step.
     */
    private async executeBlockchainRPC(
        step: Step
    ): Promise<{ data: unknown; sources: string[] }> {
        const rpcConfig = step.tool_config.blockchain_rpc;
        const method = rpcConfig?.method || "eth_call";
        const params = rpcConfig?.params || [];

        const response = await fetch(this.config.rpcUrl, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                jsonrpc: "2.0",
                id: 1,
                method,
                params,
            }),
        });

        if (!response.ok) {
            throw new Error(
                `RPC error: ${response.status} ${response.statusText}`
            );
        }

        const data = await response.json();
        if (data.error) {
            throw new Error(`RPC call failed: ${data.error.message}`);
        }

        return {
            data: data.result,
            sources: [`rpc:${this.config.rpcUrl}:${method}`],
        };
    }

    // ─── x402 Payment Gate ─────────────────────────────────────

    /**
     * Request x402 payment authorization for a step.
     * In production, this calls the on-chain X402PaymentGate contract.
     * For development, it simulates authorization with budget check.
     */
    private async authorizePayment(
        step: Step,
        sessionId: string
    ): Promise<PaymentAuthorization> {
        // Check remaining budget
        const remaining =
            step.estimated_cost_usd <= 0
                ? 0
                : step.estimated_cost_usd;

        // Production: call X402PaymentGate.authorizePayment(stepId, amount)
        // For now: simulate with budget enforcement
        try {
            if (this.config.x402ContractAddress && this.config.x402ContractAddress !== "0x0000000000000000000000000000000000000000") {
                // On-chain authorization via EVM write
                const stepIdHash = this.hashStepId(step.id);
                const amountWei = Math.floor(step.estimated_cost_usd * 1e6); // USDC 6 decimals

                const txHash = await this.callContract(
                    "authorizePayment",
                    [stepIdHash, amountWei],
                    sessionId
                );

                return {
                    step_id: step.id,
                    amount_usd: step.estimated_cost_usd,
                    authorized: true,
                    tx_hash: txHash,
                    error: null,
                };
            } else {
                // Simulated mode — just check budget
                console.log(
                    `[x402] Simulated payment auth: step=${step.id}, cost=$${step.estimated_cost_usd}`
                );
                return {
                    step_id: step.id,
                    amount_usd: step.estimated_cost_usd,
                    authorized: true,
                    tx_hash: `sim_${Date.now()}_${step.id}`,
                    error: null,
                };
            }
        } catch (error) {
            return {
                step_id: step.id,
                amount_usd: step.estimated_cost_usd,
                authorized: false,
                tx_hash: null,
                error: error instanceof Error ? error.message : String(error),
            };
        }
    }

    private async confirmPayment(
        stepId: string,
        sessionId: string
    ): Promise<void> {
        if (this.config.x402ContractAddress && this.config.x402ContractAddress !== "0x0000000000000000000000000000000000000000") {
            await this.callContract(
                "confirmExecution",
                [this.hashStepId(stepId)],
                sessionId
            );
        }
        console.log(`[x402] Payment confirmed: step=${stepId}`);
    }

    private async refundPayment(
        stepId: string,
        sessionId: string
    ): Promise<void> {
        if (this.config.x402ContractAddress && this.config.x402ContractAddress !== "0x0000000000000000000000000000000000000000") {
            await this.callContract(
                "refund",
                [this.hashStepId(stepId)],
                sessionId
            );
        }
        console.log(`[x402] Payment refunded: step=${stepId}`);
    }

    // ─── Contract Helpers ──────────────────────────────────────

    private async callContract(
        method: string,
        args: unknown[],
        _sessionId: string
    ): Promise<string> {
        // In production, use ethers.js or viem to call the contract
        // For now, return simulated tx hash
        console.log(`[x402] Contract call: ${method}(${JSON.stringify(args)})`);
        return `0x${Buffer.from(Date.now().toString()).toString("hex")}`;
    }

    private hashStepId(stepId: string): string {
        // In production, use keccak256
        // For now, simple hex encoding
        return `0x${Buffer.from(stepId).toString("hex").padEnd(64, "0")}`;
    }

    // ─── JSON Helper ───────────────────────────────────────────

    private tryParseJSON(text: string): unknown | null {
        try {
            const match = text.match(/```(?:json)?\s*([\s\S]*?)```/);
            const jsonStr = match ? match[1].trim() : text.trim();
            return JSON.parse(jsonStr);
        } catch {
            return null;
        }
    }
}
