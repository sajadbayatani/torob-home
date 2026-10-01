<script setup lang="ts">
/**
 * Thinking states: the Persian sentence that says what a running search is doing.
 *
 * Translated from a React reference into Vue, with the same behaviour and none of
 * its machinery — no animation library, no state hook, no second search request.
 * This component **does not own the search**. It is handed the states and which one
 * is active, and it draws that; the parent decides what is true.
 *
 * Three things it has to get right, and each is a layout question rather than an
 * animation question:
 *
 * * **The box must not move.** The text is Persian, and the sentences are different
 *   lengths, so a naive swap reflows the search bar on every state change. Two
 *   measures fix it together: an invisible copy of the *longest* sentence holds the
 *   width open, and the outgoing and incoming sentences are stacked in one grid
 *   cell so the height is the taller of the two, not the sum.
 * * **The swap must be legible.** Outgoing rises and blurs out, incoming rises in,
 *   both over 150ms, so the eye follows one line of text upwards.
 * * **Reduced motion must leave the sentence readable.** The global
 *   `prefers-reduced-motion` rule shortens the animation to a single 0.01ms frame,
 *   which parks the 250% gradient at its *end* position while the text is still
 *   transparent — so shortening alone would leave the sentence clipped away and
 *   unreadable. The fallback below drops the gradient and gives the text its own
 *   colour, which is why it is more than a shorter duration.
 * * **A screen reader must hear the sentence once, not sixty times a second.**
 *   Only the incoming sentence is inside the live region; the outgoing copy and
 *   the width-holding copy are both `aria-hidden`, and the shimmer is a background
 *   on the text rather than text that changes.
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'

export interface ThinkingState {
  id: string
  text: string
}

const props = withDefaults(
  defineProps<{
    /** Every state the caller can show, in the order it can show them. */
    states: ThinkingState[]
    /** Which one is active. `-1`, or out of range, shows nothing. */
    activeIndex: number
    visible?: boolean
  }>(),
  { visible: true },
)

/** The index of the sentence being animated out, or -1 when there is none. */
const outgoingIndex = ref(-1)
/**
 * True for one frame after a change, while the incoming sentence still wears its
 * start styles.
 *
 * Without it the incoming sentence is written already in its resting styles in the
 * same tick the class list changes, so the browser has no earlier state to
 * transition *from* and the swap reads as a cut rather than a move.
 */
const entering = ref(false)
let frame: number | undefined

const active = computed<ThinkingState | null>(
  () => props.states[props.activeIndex] ?? null,
)
const outgoing = computed<ThinkingState | null>(
  () => (outgoingIndex.value >= 0 ? (props.states[outgoingIndex.value] ?? null) : null),
)

/**
 * The longest sentence, used only to hold the width open.
 *
 * Measured by rendered length rather than by a character count alone: Persian is
 * cursive, so joining letters changes how wide a word is, and the sentences differ
 * in words as well as letters. Counting characters is close enough for a
 * reservation — it errs wide, which is the safe direction, because too wide costs a
 * few blank pixels and too narrow makes the bar jump. No width is hardcoded.
 */
const widest = computed<ThinkingState | null>(() => {
  let best: ThinkingState | null = null
  let longest = -1
  for (const state of props.states) {
    const length = state.text.length
    if (length > longest) {
      longest = length
      best = state
    }
  }
  return best
})

/**
 * Keep the old sentence mounted until its own transition has finished.
 *
 * It is released when the browser says the opacity transition ended, not when a
 * timer says so. That matters for two reasons: the fade really is 150ms because
 * the styles say it is, and nothing in this component decides *when* a state
 * arrives — the parent does, and a slow request keeps its sentence for as long as
 * it is pending.
 *
 * Without keeping the element mounted at all, the outgoing sentence would be
 * removed on the same tick it is given its final styles and the browser would
 * never paint an intermediate frame, so the transition would be a no-op and the
 * swap would look like a cut.
 */
watch(
  () => props.activeIndex,
  (next, previous) => {
    if (frame !== undefined) {
      cancelAnimationFrame(frame)
      frame = undefined
    }
    // the first render, and any render that is not actually a change, has nothing
    // to cross-fade: a sentence appearing for the first time should simply be there
    if (previous === undefined || previous < 0 || next === previous) {
      outgoingIndex.value = -1
      entering.value = false
      return
    }
    outgoingIndex.value = previous
    entering.value = true
    // one frame in the start styles, so the browser has an earlier state to
    // transition from; this is a frame boundary, not a duration
    frame = requestAnimationFrame(() => {
      entering.value = false
      frame = undefined
    })
  },
  { immediate: true },
)

/** The outgoing sentence finished fading; nothing is holding it any more. */
function onOutgoingEnd() {
  outgoingIndex.value = -1
}

onBeforeUnmount(() => {
  if (frame !== undefined) cancelAnimationFrame(frame)
})

/** Rotation follows the active state, as the reference does. */
const sparkleRotation = computed(() => props.activeIndex * 90)
</script>
<template>
  <!--
    `role="status"` is a polite live region: the sentence is announced when it
    changes and not while it animates, because nothing inside it changes text
    during the animation — the shimmer moves a background, and the outgoing copy is
    hidden from assistive technology.
  -->
  <div
    v-if="visible && active"
    role="status"
    dir="rtl"
    class="flex min-w-0 items-center gap-2 text-sm text-muted-foreground
           animate-thinking-breathe motion-reduce:animate-none"
    data-test="thinking-states"
  >
    <!--
      The sparkle, in two motions on two elements so they compose instead of
      fighting: the wrapper breathes (a few percent of scale, a little opacity) and
      the icon itself turns to the active state's angle. One element cannot do both
      — a keyframe on `transform` would overwrite the angle every frame.

      The turn is 90° per state and is *transitioned*, so a state change reads as a
      quarter turn rather than a jump. `aria-hidden`: it is decoration, and a screen
      reader has no business hearing either motion.
    -->
    <span class="shrink-0 animate-thinking-pulse motion-reduce:animate-none">
      <svg
        aria-hidden="true"
        viewBox="0 0 20 20"
        fill="none"
        class="h-4 w-4 text-primary transition-transform duration-long ease-motion
               motion-reduce:transition-none"
        :style="{ transform: `rotate(${sparkleRotation}deg)` }"
        data-test="thinking-sparkle"
      >
        <path
          d="M10 2.5c.55 3.1 1.9 4.45 5 5-3.1.55-4.45 1.9-5 5-.55-3.1-1.9-4.45-5-5 3.1-.55 4.45-1.9 5-5Z"
          fill="currentColor"
        />
        <path
          d="M15.5 12.5c.3 1.7 1.05 2.45 2.75 2.75-1.7.3-2.45 1.05-2.75 2.75-.3-1.7-1.05-2.45-2.75-2.75 1.7-.3 2.45-1.05 2.75-2.75Z"
          fill="currentColor"
        />
      </svg>
    </span>

    <!--
      One grid cell, three layers in it. The invisible copy sets the width, the
      outgoing and incoming sentences are absolutely centred on top of it, and the
      cell is `relative` with a fixed inset so nothing reflows while they cross.
    -->
    <span class="relative min-w-0 flex-1" data-test="thinking-stack">
      <span
        v-if="widest"
        aria-hidden="true"
        class="invisible block truncate whitespace-nowrap"
        data-test="thinking-sizer"
        >{{ widest.text }}</span
      >

      <!--
        The outgoing sentence, mid-cross-fade. It is pinned to the same cell and
        hidden from assistive technology, so the announcement stays one sentence.
        Under reduced motion the whole layer is dropped rather than faded.
      -->
      <span
        v-if="outgoing"
        aria-hidden="true"
        class="pointer-events-none absolute inset-0 flex items-center truncate whitespace-nowrap
               text-muted-foreground transition-[opacity,transform,filter]
               duration-motion ease-decelerate opacity-0 blur-[2px] -translate-y-[6px]
               motion-reduce:hidden"
        data-test="thinking-outgoing"
        @transitionend="onOutgoingEnd"
        >{{ outgoing.text }}</span
      >

      <!--
        The live sentence, and the only one in the region. Its start styles are the
        ones the reference describes — 6px low, blurred, transparent — and `entering`
        drops them on the frame after a change, so the browser has an earlier state
        to transition from and the swap is a move rather than a cut.
      -->
        <span
          class="absolute inset-0 flex items-center truncate whitespace-nowrap
                bg-gradient-to-l from-muted-foreground via-foreground to-muted-foreground
                bg-shimmer bg-clip-text text-transparent animate-thinking-shimmer
                transition-[opacity,transform,filter] duration-motion ease-decelerate
                motion-reduce:animate-none motion-reduce:bg-none
                motion-reduce:text-muted-foreground motion-reduce:blur-0
                motion-reduce:transition-none"
          :class="
            entering
              ? 'translate-y-[6px] opacity-0 blur-[2px]'
              : 'translate-y-0 opacity-100 blur-0'
          "
          data-test="thinking-active"
        >
          <span>{{ active.text }}</span>
          <span
            aria-hidden="true"
            class="thinking-dots"
          >
            <span>.</span><span>.</span><span>.</span>
          </span>
        </span>
    </span>
  </div>
</template>
