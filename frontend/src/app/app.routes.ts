import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', redirectTo: 'compare', pathMatch: 'full' },
  {
    path: 'compare',
    loadComponent: () =>
      import('./features/comparison/comparison.component').then((m) => m.ComparisonComponent),
  },
  { path: '**', redirectTo: 'compare' },
];
