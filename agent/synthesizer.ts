// ─────────────────────────────────────────────────────────────
// Pay-Per-Thought Agent — Phase 3: Synthesizer
// ─────────────────────────────────────────────────────────────
// Aggregates verified step results into a final structured
// research output. Labels sources, assumptions, confidence,
// and produces the canonical JSON response.
// ─────────────────────────────────────────────────────────────

import Anthropic from "@anthropic-ai/sdk";
import {
    StepResult,
    SynthesisResult,
    AgentResponse,
    KeyFinding,
    SourceReference,
} from "./types";

// ─── Synthesizer Class ───────────────────────────────────────

export class Synthesizer {
    private anthropic: Anthropic;
    private model: string;

    constructor(apiKey: string, model: string = "claude-sonnet-4-20250514") {
        this.anthropic = new Anthropic({ apiKey });
        this.model = model;
    }

    /**
     * Synthesize step results into a final structured research output.
     */
    async synthesize(
        query: string,
        stepResults: StepResult[],
        totalSpent: number,
        wasHalted: boolean,
        sessionId: string
    ): Promise<AgentResponse> {
        const completedSteps = stepResults.filter(
            (r) => r.status === "completed"
        );

        // Build evidence context from completed steps
        const evidence = completedSteps
            .map(
                (r) =>
                    `### Step ${r.index} (${r.tool}):\n${JSON.stringify(r.output, null, 2)}\nSources: ${r.sources.join(", ")}`
            )
            .join("\n\n---\n\n");

        // All sources across all steps
        const allSources = completedSteps.flatMap((r) => r.sources);

        // Use Claude to synthesize
        const response = await this.anthropic.messages.create({
            model: this.model,
            max_tokens: 2048,
            system: `You are a research synthesis engine. Given evidence from multiple research steps, produce a comprehensive answer.

You must output ONLY valid JSON matching this exact schema:
{
  "answer": "Comprehensive answer to the research query",
  "confidence": "high" | "medium" | "low",
  "key_findings": [
    {
      "claim": "A specific finding",
      "evidence": "Supporting evidence",
      "source": "Where this came from",
      "confidence": "high" | "medium" | "low"
    }
  ],
  "assumptions": ["Any assumptions made"],
  "limitations": ["Any limitations of the analysis"]
}

Rules:
- Base everything on the provided evidence
- Clearly separate facts from inference
- If data is incomplete (execution was halted), state this
- Be concise but comprehensive`,
            messages: [
                {
                    role: "user",
                    content: `Research query: "${query}"\n\n${wasHalted ? "⚠️ EXECUTION WAS HALTED DUE TO BUDGET CONSTRAINTS. Results are partial.\n\n" : ""}Evidence from ${completedSteps.length} completed steps:\n\n${evidence}`,
                },
            ],
        });

        const text =
            response.content[0].type === "text" ? response.content[0].text : "";

        const synthesis = this.parseJSON(text);

        // Build source references
        const sourceRefs: SourceReference[] = this.deduplicateSources(allSources);

        // Build final synthesis result
        const synthesisResult: SynthesisResult = {
            answer: synthesis.answer || "Unable to synthesize results",
            confidence: synthesis.confidence || "low",
            key_findings: (synthesis.key_findings || []).map(
                (f: KeyFinding) => ({
                    claim: f.claim,
                    evidence: f.evidence,
                    source: f.source,
                    confidence: f.confidence || "medium",
                })
            ),
            assumptions: synthesis.assumptions || [],
            limitations: synthesis.limitations || [],
            sources: sourceRefs,
            total_cost_usd: totalSpent,
            steps_executed: completedSteps.length,
            steps_total: stepResults.length,
            was_halted: wasHalted,
        };

        // Build the canonical agent response
        return {
            status: wasHalted ? "halted" : "completed",
            session_id: sessionId,
            query,
            current_step: wasHalted
                ? `Halted at step ${stepResults.length}`
                : "synthesis_complete",
            estimated_remaining_budget: 0,
            plan: null, // Omitted in final output for conciseness
            actions: stepResults,
            results: synthesisResult,
            sources: allSources,
            notes: wasHalted
                ? "Execution halted due to budget exhaustion. Results are partial."
                : `Research completed. ${completedSteps.length} steps executed.`,
            timestamp: new Date().toISOString(),
        };
    }

    // ─── Helpers ─────────────────────────────────────────────

    private deduplicateSources(sources: string[]): SourceReference[] {
        const unique = [...new Set(sources)];
        return unique.map((source) => {
            const isUrl = source.startsWith("http");
            return {
                url: isUrl ? source : "",
                title: isUrl ? new URL(source).hostname : source,
                relevance: "primary",
                accessed_at: new Date().toISOString(),
            };
        });
    }

    private parseJSON(text: string): Record<string, unknown> {
        try {
            const match = text.match(/```(?:json)?\s*([\s\S]*?)```/);
            const jsonStr = match ? match[1].trim() : text.trim();
            return JSON.parse(jsonStr);
        } catch {
            return {
                answer: text,
                confidence: "low",
                key_findings: [],
                assumptions: ["Failed to parse structured response"],
                limitations: ["Output was not structured JSON"],
            };
        }
    }
}
