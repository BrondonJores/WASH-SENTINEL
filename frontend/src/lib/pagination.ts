/**
 * Pagination des listes admin — source unique (LOT 11 anti-valeurs-en-dur).
 *
 * Parité d'affichage avec wash.php `pagination.default` (20) : le front
 * passe toujours `per_page` explicitement, le défaut backend ne s'applique
 * donc jamais — les deux valeurs doivent rester égales.
 */
export const DEFAULT_PER_PAGE = 20;
