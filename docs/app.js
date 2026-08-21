/* ─── Stonewall Showcase — Interactive Engine ─── */

(function () {
  'use strict';

  // ─── Particle / Spark Canvas ───
  const canvas = document.getElementById('sparks');
  if (canvas) {
    const ctx = canvas.getContext('2d');
    let particles = [];
    const PARTICLE_COUNT = 60;
    const COLORS = [
      'rgba(209, 160, 106, 0.6)',
      'rgba(209, 160, 106, 0.3)',
      'rgba(119, 167, 217, 0.5)',
      'rgba(119, 167, 217, 0.25)',
      'rgba(244, 234, 219, 0.2)',
    ];

    function resize() {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    }

    function createParticle() {
      return {
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        size: Math.random() * 2.5 + 0.5,
        speedX: (Math.random() - 0.5) * 0.4,
        speedY: (Math.random() - 0.5) * 0.3 - 0.15,
        color: COLORS[Math.floor(Math.random() * COLORS.length)],
        life: Math.random() * 200 + 100,
        maxLife: 0,
        pulse: Math.random() * Math.PI * 2,
        pulseSpeed: Math.random() * 0.02 + 0.005,
      };
    }

    function initParticles() {
      particles = [];
      for (let i = 0; i < PARTICLE_COUNT; i++) {
        const p = createParticle();
        p.maxLife = p.life;
        particles.push(p);
      }
    }

    function drawParticles() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      for (let i = particles.length - 1; i >= 0; i--) {
        const p = particles[i];
        p.x += p.speedX;
        p.y += p.speedY;
        p.life--;
        p.pulse += p.pulseSpeed;

        const alpha = Math.min(1, p.life / p.maxLife) * (0.5 + 0.5 * Math.sin(p.pulse));
        if (p.life <= 0 || p.x < -10 || p.x > canvas.width + 10 || p.y < -10 || p.y > canvas.height + 10) {
          particles[i] = createParticle();
          particles[i].maxLife = particles[i].life;
          continue;
        }

        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size * (0.8 + 0.2 * Math.sin(p.pulse)), 0, Math.PI * 2);
        ctx.fillStyle = p.color.replace(/[\d.]+\)$/, (alpha * 0.8).toFixed(2) + ')');
        ctx.fill();

        // Glow
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size * 3, 0, Math.PI * 2);
        ctx.fillStyle = p.color.replace(/[\d.]+\)$/, (alpha * 0.15).toFixed(2) + ')');
        ctx.fill();
      }
      requestAnimationFrame(drawParticles);
    }

    resize();
    window.addEventListener('resize', resize);
    initParticles();
    drawParticles();
  }

  // ─── Scroll Reveal (Intersection Observer) ───
  const reveals = document.querySelectorAll('.reveal');
  const revealObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('visible');
          // Trigger counters when facts/metrics become visible
          entry.target.querySelectorAll('.counter:not(.done)').forEach(startCounter);
          // Trigger metric bars
          entry.target.querySelectorAll('.metric__bar').forEach((bar) => {
            bar.closest('.metric').classList.add('counted');
          });
        }
      });
    },
    { threshold: 0.15, rootMargin: '0px 0px -40px 0px' }
  );
  reveals.forEach((el) => revealObserver.observe(el));

  // Also observe individual metrics and facts that aren't inside .reveal
  document.querySelectorAll('.metric, .fact').forEach((el) => {
    const obs = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.querySelectorAll('.counter:not(.done)').forEach(startCounter);
            entry.target.classList.add('counted');
          }
        });
      },
      { threshold: 0.3 }
    );
    obs.observe(el);
  });

  // ─── Animated Counters ───
  function startCounter(el) {
    if (el.classList.contains('done')) return;
    const target = parseInt(el.dataset.target, 10);
    const suffix = el.dataset.suffix || '';
    const duration = 1500;
    const start = performance.now();

    function tick(now) {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      // Ease out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      const current = Math.round(eased * target);
      el.textContent = current + suffix;
      if (progress < 1) {
        requestAnimationFrame(tick);
      } else {
        el.textContent = target + suffix;
        el.classList.add('done');
        // Set bar width for metric parents
        const metricBar = el.closest('.metric')?.querySelector('.metric__bar');
        if (metricBar) {
          metricBar.style.setProperty('--bar-w', metricBar.dataset.width + '%');
        }
      }
    }
    requestAnimationFrame(tick);
  }

  // ─── Module Card Expand/Collapse ───
  document.querySelectorAll('.module-card').forEach((card) => {
    card.addEventListener('click', () => {
      const isExpanded = card.dataset.expanded === 'true';
      // Collapse all others
      document.querySelectorAll('.module-card').forEach((c) => (c.dataset.expanded = 'false'));
      card.dataset.expanded = isExpanded ? 'false' : 'true';
    });

    card.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        card.click();
      }
    });
  });

  // ─── Card Glow Follow Mouse ───
  document.querySelectorAll('.card-glow').forEach((glow) => {
    const parent = glow.parentElement;
    parent.addEventListener('mousemove', (e) => {
      const rect = parent.getBoundingClientRect();
      const x = ((e.clientX - rect.left) / rect.width) * 100;
      const y = ((e.clientY - rect.top) / rect.height) * 100;
      glow.style.setProperty('--mx', x + '%');
      glow.style.setProperty('--my', y + '%');
    });
  });

  // ─── Metric Bar Width Setup ───
  document.querySelectorAll('.metric__bar').forEach((bar) => {
    bar.style.setProperty('--bar-w', bar.dataset.width + '%');
  });

  // ─── Mobile Nav Toggle ───
  const navToggle = document.querySelector('.nav-toggle');
  const topnav = document.querySelector('.topnav');
  if (navToggle && topnav) {
    navToggle.addEventListener('click', () => {
      const isOpen = topnav.classList.toggle('open');
      navToggle.setAttribute('aria-expanded', isOpen);
    });
  }

  // ─── Smooth active nav highlighting ───
  const sections = document.querySelectorAll('section[id]');
  const navLinks = document.querySelectorAll('.topnav a[href^="#"]');

  function updateActiveNav() {
    let current = '';
    sections.forEach((section) => {
      const top = section.offsetTop - 120;
      if (window.scrollY >= top) {
        current = section.getAttribute('id');
      }
    });
    navLinks.forEach((link) => {
      link.style.color = link.getAttribute('href') === '#' + current ? 'var(--text)' : '';
    });
  }

  window.addEventListener('scroll', updateActiveNav, { passive: true });
  updateActiveNav();

  // ─── Pipeline step animation on scroll ───
  const pipelineSteps = document.querySelectorAll('.pipeline__step');
  if (pipelineSteps.length) {
    const pipeObs = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            const steps = entry.target.querySelectorAll('.pipeline__step');
            steps.forEach((step, i) => {
              setTimeout(() => {
                step.style.opacity = '1';
                step.style.transform = 'translateY(0)';
              }, i * 120);
            });
            const arrows = entry.target.querySelectorAll('.pipeline__arrow');
            arrows.forEach((arrow, i) => {
              setTimeout(() => {
                arrow.style.opacity = '1';
                arrow.style.transform = 'scaleX(1)';
              }, i * 120 + 60);
            });
          }
        });
      },
      { threshold: 0.3 }
    );
    const pipeline = document.querySelector('.pipeline');
    if (pipeline) {
      // Set initial hidden state
      pipelineSteps.forEach((step) => {
        step.style.opacity = '0';
        step.style.transform = 'translateY(20px)';
        step.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
      });
      document.querySelectorAll('.pipeline__arrow').forEach((arrow) => {
        arrow.style.opacity = '0';
        arrow.style.transform = 'scaleX(0)';
        arrow.style.transformOrigin = 'left';
        arrow.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
      });
      pipeObs.observe(pipeline);
    }
  }
})();
