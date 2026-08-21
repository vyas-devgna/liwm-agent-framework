/**
 * LIWM Official Website - Main JS
 * Minimal, zero-dependency interactions.
 */

document.addEventListener('DOMContentLoaded', () => {
  // Intersection Observer for scroll animations
  const observerOptions = {
    root: null,
    rootMargin: '0px',
    threshold: 0.1
  };

  const observer = new IntersectionObserver((entries, observer) => {
    entries.forEach(entry => {
      // Respect prefers-reduced-motion
      const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      
      if (entry.isIntersecting && !prefersReducedMotion) {
        entry.target.classList.add('is-visible');
        // Stop observing once animated
        observer.unobserve(entry.target);
      } else if (prefersReducedMotion) {
        // Immediately show if motion is reduced
        entry.target.classList.add('is-visible');
        entry.target.style.opacity = '1';
        entry.target.style.transform = 'none';
        observer.unobserve(entry.target);
      }
    });
  }, observerOptions);

  // Apply to elements that should animate on scroll
  const animatedElements = document.querySelectorAll('.technical-box, .section-header');
  animatedElements.forEach(el => {
    el.classList.add('animate-fade-in');
    observer.observe(el);
  });
});
