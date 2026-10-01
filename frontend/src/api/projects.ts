import { http } from './client'
import type {
  ComplementaryResponse,
  ProjectOptimizeResponse,
  InterpretedIntent,
  ProjectAnalyzeResponse,
  ProjectAnalysis,
  ProjectConstraints,
  ProjectTemplate,
  Quality,
} from '@/types/api'

export const projectsApi = {
  /**
   * Analyse a project.
   *
   * Pass `interpretation` when one already exists — `/search/interpret` returns
   * one for every query, and sending it here means the backend reuses it instead
   * of inferring the same sentence a second time. The backend re-validates it
   * either way; this is a hand-off, not a decision.
   */
  analyze(
    query: string,
    constraints: ProjectConstraints = {},
    interpretation?: InterpretedIntent,
  ) {
    return http.post<ProjectAnalyzeResponse>('/projects/analyze', {
      query,
      constraints,
      ...(interpretation ? { interpretation } : {}),
    })
  },
  detail(analysisId: string) {
    return http.get<ProjectAnalysis>(`/projects/${analysisId}`)
  },
  /**
   * The one optimization action.
   *
   * Takes the values exactly as they stand in the form. A field the user
   * cleared is sent as `null`, which the backend reads as *cleared* — it does not
   * fall back to a value the user entered earlier. Nothing is added to or removed
   * from the basket unless `apply` is set, and even then only the proposed
   * replacements are carried out.
   */
  optimize(
    analysisId: string,
    values: {
      area_m2: number | null
      quality: Quality | null
      budget: number | null
      style: string | null
    },
    apply = false,
  ) {
    return http.post<ProjectOptimizeResponse>(
      `/projects/${analysisId}/optimize?apply=${apply ? 'true' : 'false'}`,
      values,
    )
  },
  reanalyze(analysisId: string, constraints: ProjectConstraints) {
    return http.post<ProjectAnalyzeResponse>(`/projects/${analysisId}/reanalyze`, { constraints })
  },
  /**
   * Products that complete the whole project, not just one product.
   *
   * The backend merges the candidates of every chosen item into one bounded
   * pool and asks the model a single question, so this costs one call however
   * many items the project has.
   */
  complementary(analysisId: string, limit = 6) {
    return http.get<ComplementaryResponse>(`/projects/${analysisId}/complementary`, { limit })
  },
  templates() {
    return http.get<ProjectTemplate[]>('/projects/templates')
  },
}
