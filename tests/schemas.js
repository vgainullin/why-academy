import { z } from 'zod';

const BaseBlockSchema = z.object({
  id: z.string(),
  type: z.string(),
});

const ReadBlockSchema = BaseBlockSchema.extend({
  type: z.literal('read'),
  title: z.string(),
  content_html: z.string().min(1),
}).passthrough();

const StepSchema = z.object({
  instruction: z.string(),
  result_equation: z.string(),
}).passthrough();

const DeriveBlockSchema = BaseBlockSchema.extend({
  type: z.literal('derive'),
  title: z.string(),
  prompt: z.string(),
  starting_equation: z.string(),
  steps: z.array(StepSchema).min(1),
}).passthrough();

const CalculateBlockSchema = BaseBlockSchema.extend({
  type: z.literal('calculate'),
  title: z.string(),
  prompt: z.string(),
  expected_value: z.number(),
  formula: z.string().optional(),
  variables: z.record(z.string(), z.number()).optional(),
}).passthrough();

const CheckSchema = z.object({
  variable: z.string(),
  expected_expr: z.string().optional(),
  tolerance: z.number().optional(),
  max_value: z.number().optional(),
}).passthrough();

const CodeBlockSchema = BaseBlockSchema.extend({
  type: z.literal('code'),
  title: z.string(),
  prompt: z.string(),
  starter_code: z.string(),
  solution_code: z.string(),
  checks: z.array(CheckSchema).min(1),
}).passthrough();

const PracticeBlockSchema = BaseBlockSchema.extend({
  type: z.literal('practice'),
  title: z.string(),
  template: z.string(),
  parameter_ranges: z.record(z.string(), z.tuple([z.number(), z.number()])),
  answer_formula: z.string(),
}).passthrough();

const OptionSchema = z.object({
  id: z.string(),
  text: z.string(),
  correct: z.boolean(),
  misconception: z.string().optional(),
}).passthrough()
  // If correct = false, misconception is required
  .refine(data => {
    if (!data.correct && !data.misconception) return false;
    return true;
  }, {
    message: "misconception is required if correct is false",
    path: ["misconception"]
  });

const ExplainBlockSchema = BaseBlockSchema.extend({
  type: z.literal('explain'),
  title: z.string(),
  prompt: z.string(),
  options: z.array(OptionSchema).min(2)
}).passthrough()
  .refine(data => data.options.filter(o => o.correct).length === 1, {
    message: "explain must have exactly one correct option",
    path: ["options"]
  });

/* --- NEW SCHEMA BLOCKS --- */

const ExploreBlockSchema = BaseBlockSchema.extend({
  type: z.literal('explore'),
  title: z.string(),
  content_html: z.string().optional(),
}).passthrough();

const PredictBlockSchema = BaseBlockSchema.extend({
  type: z.literal('predict'),
  title: z.string(),
  prompt: z.string()
}).passthrough();

const DiscoverBlockSchema = BaseBlockSchema.extend({
  type: z.literal('discover'),
  title: z.string(),
  prompt: z.string()
}).passthrough();

const CompareBlockSchema = BaseBlockSchema.extend({
  type: z.literal('compare'),
  title: z.string()
}).passthrough();

const ReconcileBlockSchema = BaseBlockSchema.extend({
  type: z.literal('reconcile'),
  title: z.string(),
  prompt: z.string()
}).passthrough();

const VaryBlockSchema = BaseBlockSchema.extend({
  type: z.literal('vary'),
  title: z.string(),
  template: z.string(),
  parameter_ranges: z.record(z.string(), z.tuple([z.number(), z.number()])),
  answer_formula: z.string()
}).passthrough();

const ConnectBlockSchema = BaseBlockSchema.extend({
  type: z.literal('connect'),
  title: z.string(),
  content_html: z.string()
}).passthrough();

const CanvasDeriveBlockSchema = BaseBlockSchema.extend({
  type: z.literal('canvas-derive'),
  title: z.string(),
  prompt: z.string(),
  starting_equation: z.string(),
  target_equation: z.string()
}).passthrough();

const HandwriteBlockSchema = BaseBlockSchema.extend({
  type: z.literal('handwrite'),
  title: z.string(),
  prompt: z.string(),
  starting_equation: z.string()
}).passthrough();

export const AnyBlockSchema = z.discriminatedUnion('type', [
  ReadBlockSchema,
  DeriveBlockSchema,
  CalculateBlockSchema,
  CodeBlockSchema,
  PracticeBlockSchema,
  ExplainBlockSchema,
  ExploreBlockSchema,
  PredictBlockSchema,
  DiscoverBlockSchema,
  CompareBlockSchema,
  ReconcileBlockSchema,
  VaryBlockSchema,
  ConnectBlockSchema,
  CanvasDeriveBlockSchema,
  HandwriteBlockSchema
]);

export const LessonSchema = z.object({
  lesson_id: z.string(),
  title: z.string(),
  description: z.string(),
  blocks: z.array(AnyBlockSchema),
}).passthrough();
