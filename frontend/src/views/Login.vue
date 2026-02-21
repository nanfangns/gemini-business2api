<template>
  <div class="relative flex min-h-screen items-center justify-center overflow-hidden bg-[#1a0b0b] px-4 font-sans selection:bg-amber-400/30 selection:text-white">
    <!-- 动态渐变背景 -->
    <div class="absolute inset-0 z-0">
      <div class="absolute -left-[10%] -top-[10%] h-[70%] w-[70%] rounded-full bg-rose-500/18 blur-[120px]"></div>
      <div class="absolute -right-[5%] -bottom-[5%] h-[60%] w-[60%] rounded-full bg-amber-400/14 blur-[100px]"></div>
      <div class="absolute left-1/2 top-1/2 h-[50%] w-[50%] -translate-x-1/2 -translate-y-1/2 rounded-full bg-red-400/8 blur-[150px]"></div>
    </div>

    <div class="relative z-10 w-full max-w-[420px]">
      <!-- 登录卡片 (Glassmorphism) -->
      <div class="overflow-hidden rounded-[2.5rem] border border-white/[0.08] bg-white/[0.02] p-8 md:p-12 backdrop-blur-2xl transition-all duration-500 hover:border-white/[0.12] hover:bg-white/[0.03]">
        <div class="mb-12 text-center">
          <div class="mb-8 flex justify-center">
            <div class="relative h-20 w-20">
              <!-- Logo 发光底座 -->
              <div class="absolute inset-0 animate-pulse rounded-full bg-rose-500/25 blur-xl"></div>
              <img src="/logo.svg" alt="Logo" class="relative h-20 w-20 drop-shadow-2xl" />
            </div>
          </div>
          <h1 class="bg-gradient-to-b from-amber-100 via-amber-200 to-rose-100 bg-clip-text text-3xl font-bold tracking-tight text-transparent">Gemini Business</h1>
          <p class="mt-3 text-[10px] font-bold uppercase tracking-[0.3em] text-amber-100/60">Spring Festival Console</p>
        </div>

        <form @submit.prevent="handleLogin" class="space-y-8">
          <div class="space-y-3">
            <label for="password" class="ml-1 flex items-center gap-2 text-[10px] font-bold uppercase tracking-wider text-white/40">
              <span class="h-1 w-1 rounded-full bg-amber-400"></span>
              Administrative Secret
            </label>
            <div class="relative">
              <input
                id="password"
                v-model="password"
                type="password"
                required
                class="peer w-full rounded-2xl border border-white/[0.1] bg-white/[0.05] px-6 py-4 text-sm text-white placeholder-white/25
                       outline-none transition-all duration-300 focus:border-amber-300/60 focus:bg-white/[0.09] focus:ring-[6px] focus:ring-amber-400/15"
                placeholder="Enter access key..."
                :disabled="isLoading"
              />
            </div>
          </div>

          <div v-if="errorMessage" class="animate-in fade-in slide-in-from-top-2 rounded-2xl border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-center text-[11px] font-semibold text-rose-300 backdrop-blur-sm">
            {{ errorMessage }}
          </div>

          <button
            type="submit"
            :disabled="isLoading || !password"
            class="group relative w-full overflow-hidden rounded-2xl bg-gradient-to-r from-rose-500 via-red-500 to-amber-400 px-8 py-4 text-sm font-black tracking-widest text-white transition-all
                   hover:scale-[1.02] hover:shadow-[0_0_34px_rgba(251,191,36,0.35)] active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-20 disabled:hover:scale-100 disabled:hover:shadow-none"
          >
            <div class="relative flex items-center justify-center gap-3">
              <span v-if="!isLoading">LOG IN</span>
              <template v-else>
                <svg class="h-4 w-4 animate-spin" viewBox="0 0 24 24">
                  <circle class="opacity-20" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle>
                  <path class="opacity-80" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4"></path>
                </svg>
                <span>VERIFYING...</span>
              </template>
            </div>
          </button>
        </form>

        <div class="mt-12 flex flex-col items-center gap-6 border-t border-white/[0.05] pt-10 text-[9px] font-bold uppercase tracking-[0.25em] text-white/20">
          <div class="flex items-center gap-8">
            <a href="https://github.com/Dreamy-rain/gemini-business2api" target="_blank" class="transition-all hover:text-white/50">GitHub Repository</a>
            <span class="h-1 w-1 rounded-full bg-white/10"></span>
            <span class="text-white/10">v2.0.4 PRO</span>
          </div>
        </div>
      </div>
    </div>
    
    <!-- 装饰性渐变线条 -->
    <div class="absolute bottom-[-10%] left-[-5%] h-[1px] w-[40%] -rotate-12 bg-gradient-to-r from-transparent via-rose-400/40 to-transparent"></div>
    <div class="absolute top-[20%] right-[-10%] h-[1px] w-[30%] rotate-45 bg-gradient-to-r from-transparent via-amber-300/40 to-transparent"></div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()

const password = ref('')
const errorMessage = ref('')
const isLoading = ref(false)

async function handleLogin() {
  if (!password.value) return

  errorMessage.value = ''
  isLoading.value = true

  try {
    await authStore.login(password.value)
    router.push({ name: 'dashboard' })
  } catch (error: any) {
    errorMessage.value = error.message || 'Access Denied • Invalid Key'
  } finally {
    isLoading.value = false
  }
}
</script>
