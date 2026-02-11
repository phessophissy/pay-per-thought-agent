// ─────────────────────────────────────────────────────────────
// Pay-Per-Thought Agent — Phase 1: Planner
// ─────────────────────────────────────────────────────────────
// Decomposes a research query into atomic, metered execution steps.
// Each step has a tool assignment, cost estimate, and dependency chain.
// ─────────────────────────────────────────────────────────────

import Anthropic from "@anthropic-ai/sdk";
import { v4 as uuidv4 } from "uuid";
import {
    ExecutionPlan,
    Step,
    ToolType,
    ToolConfig,
    COST_PER_TOOL,
} from "./types";

// ─── Planning Prompt ─────────────────────────────────────────

const PLANNING_SYSTEM_PROMPT = `You are a research planning engine. Your job is to decompose a research query into a minimal set of atomic execution steps.

Each step must specify:
- A clear description of what to do
- Which tool to use: "anthropic" (reasoning/analysis), "tavily" (web search), "blockchain_rpc" (on-chain data)
- Dependencies on previous steps (by step ID)

Rules:
1. Minimize the number of steps. Do not over-decompose.
2. Use "tavily" for any factual data retrieval from the web.
3. Use "blockchain_rpc" for on-chain data (TVL, balances, contract state).
4. Use "anthropic" for reasoning, analysis, and synthesis sub-tasks.
5. Steps should be ordered by dependency.
6. Return ONLY valid JSON matching the schema below.

Output JSON schema:
{
  "steps": [
    {
      "description": "string",
      "tool": "anthropic" | "tavily" | "blockchain_rpc",
      "depends_on_indices": [0]  // indices of steps this depends on, empty array if none
    }
  ]
}`;

// ─── Planner Class ───────────────────────────────────────────

export class Planner {
    private anthropic: Anthropic;
    private model: string;

    constructor(apiKey: string, model: string = "claude-sonnet-4-20250514") {
        this.anthropic = new Anthropic({ apiKey });
        this.model = model;
    }

    /**
     * Generate an execution plan from a research query.
     */
    async generatePlan(
        query: string,
        maxBudget: number
    ): Promise<ExecutionPlan> {
        const sessionId = uuidv4();

        // Ask Claude to decompose the query
        const response = await this.anthropic.messages.create({
            model: this.model,
            max_tokens: 2048,
            system: PLANNING_SYSTEM_PROMPT,
            messages: [
                {
                    role: "user",
                    content: `Research query: "${query}"\n\nDecompose this into atomic execution steps. Return JSON only.`,
                },
            ],
        });

        // Extract JSON from response
        const content = response.content[0];
        if (content.type !== "text") {
            throw new Error("Unexpected response type from planning LLM");
        }

        const rawPlan = this.parseJSON(content.text);

        // Build typed steps with IDs, costs, and tool configs
        const steps: Step[] = rawPlan.steps.map(
            (
                raw: {
                    description: string;
                    tool: ToolType;
                    depends_on_indices: number[];
                },
                index: number
            ) => {
                const stepId = `step_${index}_${uuidv4().slice(0, 8)}`;
                const tool = this.validateTool(raw.tool);

                return {
                    id: stepId,
                    index,
                    description: raw.description,
                    tool,
                    tool_config: this.defaultToolConfig(tool),
                    estimated_cost_usd: COST_PER_TOOL[tool],
                    depends_on: (raw.depends_on_indices || []).map(
                        (i: number) => `step_${i}_pending`
                    ),
                } satisfies Step;
            }
        );

        // Resolve dependency IDs now that all step IDs are known
        for (const step of steps) {
            step.depends_on = step.depends_on.map((dep) => {
                const depIndex = parseInt(dep.split("_")[1]);
                return steps[depIndex]?.id || dep;
            });
        }

        const totalEstimatedCost = steps.reduce(
            (sum, s) => sum + s.estimated_cost_usd,
            0
        );

        // Check budget
        if (totalEstimatedCost > maxBudget) {
            // Trim steps to fit budget
            let budget = maxBudget;
            const trimmedSteps: Step[] = [];
            for (const step of steps) {
                if (budget >= step.estimated_cost_usd) {
                    budget -= step.estimated_cost_usd;
                    trimmedSteps.push(step);
                } else {
                    break;
                }
            }
            return this.buildPlan(sessionId, query, trimmedSteps, maxBudget);
        }

        return this.buildPlan(sessionId, query, steps, maxBudget);
    }

    // ─── Helpers ─────────────────────────────────────────────

    private buildPlan(
        sessionId: string,
        query: string,
        steps: Step[],
        maxBudget: number
    ): ExecutionPlan {
        return {
            session_id: sessionId,
            query,
            steps,
            step_count: steps.length,
            total_estimated_cost: steps.reduce(
                (sum, s) => sum + s.estimated_cost_usd,
                0
            ),
            max_budget: maxBudget,
            created_at: new Date().toISOString(),
        };
    }

    private validateTool(tool: string): ToolType {
        const valid: ToolType[] = [
            "anthropic",
            "tavily",
            "blockchain_rpc",
            "reasoning",
        ];
        if (valid.includes(tool as ToolType)) return tool as ToolType;
        return "anthropic"; // fallback
    }

    private defaultToolConfig(tool: ToolType): ToolConfig {
        switch (tool) {
            case "anthropic":
            case "reasoning":
                return {
                    anthropic: { model: "claude-sonnet-4-20250514", max_tokens: 1024 },
                };
            case "tavily":
                return { tavily: { search_depth: "advanced", max_results: 5 } };
            case "blockchain_rpc":
                return {
                    blockchain_rpc: { chain_id: 1, method: "eth_call", params: [] },
                };
        }
    }

    private parseJSON(text: string): { steps: Array<{ description: string; tool: string; depends_on_indices: number[] }> } {
        // Try to extract JSON from markdown code blocks or raw text
        const jsonMatch = text.match(/```(?:json)?\s*([\s\S]*?)```/);
        const jsonStr = jsonMatch ? jsonMatch[1].trim() : text.trim();
        try {
            return JSON.parse(jsonStr);
        } catch {
            throw new Error(`Failed to parse planning response as JSON: ${jsonStr.slice(0, 200)}`);
        }
    }
}
