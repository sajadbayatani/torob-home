import { createRouter, createWebHistory } from 'vue-router'

import HomeView from '@/views/HomeView.vue'
import SelectionView from '@/views/SelectionView.vue'
import ProductView from '@/views/ProductView.vue'
import ProjectView from '@/views/ProjectView.vue'
import SearchView from '@/views/SearchView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: HomeView },
    { path: '/search', name: 'search', component: SearchView },
    { path: '/product/:id', name: 'product', component: ProductView, props: true },
    { path: '/project/:id', name: 'project', component: ProjectView, props: true },
    { path: '/selections/:id', name: 'selection', component: SelectionView, props: true },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
  scrollBehavior: () => ({ top: 0 }),
})
