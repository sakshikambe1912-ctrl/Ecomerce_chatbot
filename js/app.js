// ========================================================
// ShopZone (Amazon Clone) - Application Logic
// Features: Real-time search, cart management, filters,
// hero carousel, quick-view modal, side navigation, etc.
// ========================================================

document.addEventListener('DOMContentLoaded', () => {
  // App State
  let cart = JSON.parse(localStorage.getItem('shopzone_cart')) || [];
  let currentCategory = 'All';
  let searchQuery = '';
  let currentSlide = 0;
  let heroInterval = null;

  // DOM Elements
  const heroSlider = document.getElementById('heroSlider');
  const heroPrevBtn = document.getElementById('heroPrev');
  const heroNextBtn = document.getElementById('heroNext');
  const promoGrid = document.getElementById('promoGrid');
  const dealsContainer = document.getElementById('dealsContainer');
  const productsGrid = document.getElementById('productsGrid');
  const productsCount = document.getElementById('productsCount');
  const filterPills = document.querySelectorAll('.filter-pill');
  const searchInput = document.getElementById('searchInput');
  const searchBtn = document.getElementById('searchBtn');
  const searchCategorySelect = document.getElementById('searchCategorySelect');
  
  // Cart DOM
  const cartIconBtn = document.getElementById('cartIconBtn');
  const cartBadge = document.getElementById('cartBadge');
  const cartDrawer = document.getElementById('cartDrawer');
  const cartDrawerOverlay = document.getElementById('cartDrawerOverlay');
  const cartCloseBtn = document.getElementById('cartCloseBtn');
  const cartItemsList = document.getElementById('cartItemsList');
  const cartSubtotal = document.getElementById('cartSubtotal');
  const checkoutBtn = document.getElementById('checkoutBtn');

  // Modals & Drawers DOM
  const quickViewModal = document.getElementById('quickViewModal');
  const modalCloseBtn = document.getElementById('modalCloseBtn');
  const sidebarDrawer = document.getElementById('sidebarDrawer');
  const sidebarOverlay = document.getElementById('sidebarOverlay');
  const sidebarOpenBtn = document.getElementById('sidebarOpenBtn');
  const sidebarCloseBtn = document.getElementById('sidebarCloseBtn');
  const locationBtn = document.getElementById('locationBtn');
  const locationModal = document.getElementById('locationModal');
  const locationModalClose = document.getElementById('locationModalClose');
  const locApplyBtn = document.getElementById('locApplyBtn');
  const locZipInput = document.getElementById('locZipInput');
  const locDisplay = document.getElementById('locDisplay');

  // --------------------------------------------------------
  // 1. HERO SLIDER INITIALIZATION
  // --------------------------------------------------------
  function initHeroSlider() {
    if (!heroSlider) return;
    heroSlider.innerHTML = '';

    heroBanners.forEach((banner, idx) => {
      const slide = document.createElement('div');
      slide.className = `hero-slide ${idx === 0 ? 'active' : ''}`;
      slide.style.background = banner.bgGradient;
      slide.innerHTML = `
        <div class="hero-content">
          <span class="hero-tag">${banner.tag}</span>
          <h1 class="hero-title">${banner.title}</h1>
          <p class="hero-subtitle">${banner.subtitle}</p>
          <button class="hero-btn" data-cat="${banner.categoryFilter}">${banner.cta}</button>
        </div>
      `;
      heroSlider.appendChild(slide);
    });

    // Button event listener inside banners
    heroSlider.querySelectorAll('.hero-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const cat = e.target.getAttribute('data-cat');
        filterByCategory(cat);
        scrollToProducts();
      });
    });

    startHeroAutoSlide();
  }

  function showSlide(index) {
    const slides = document.querySelectorAll('.hero-slide');
    if (!slides.length) return;
    slides.forEach(s => s.classList.remove('active'));
    currentSlide = (index + slides.length) % slides.length;
    slides[currentSlide].classList.add('active');
  }

  function startHeroAutoSlide() {
    if (heroInterval) clearInterval(heroInterval);
    heroInterval = setInterval(() => {
      showSlide(currentSlide + 1);
    }, 5500);
  }

  if (heroPrevBtn && heroNextBtn) {
    heroPrevBtn.addEventListener('click', () => {
      showSlide(currentSlide - 1);
      startHeroAutoSlide();
    });
    heroNextBtn.addEventListener('click', () => {
      showSlide(currentSlide + 1);
      startHeroAutoSlide();
    });
  }

  // --------------------------------------------------------
  // 2. RENDER 4-QUAD PROMO CARDS (Classic Amazon overlay)
  // --------------------------------------------------------
  function renderPromoCards() {
    if (!promoGrid) return;
    promoGrid.innerHTML = promoCards.map(card => `
      <div class="promo-card">
        <h2 class="promo-card-title">${card.title}</h2>
        <div class="promo-items-grid">
          ${card.items.map(item => `
            <div class="promo-sub-item" onclick="window.filterByCategory('${card.category}')">
              <img src="${item.img}" alt="${item.name}" class="promo-item-img" loading="lazy" />
              <span class="promo-item-name">${item.name}</span>
            </div>
          `).join('')}
        </div>
        <span class="promo-link" onclick="window.filterByCategory('${card.category}')">${card.linkText}</span>
      </div>
    `).join('');
  }

  // --------------------------------------------------------
  // 3. RENDER DEALS OF THE DAY SCROLL
  // --------------------------------------------------------
  function renderDeals() {
    if (!dealsContainer) return;
    const dealItems = productsData.filter(p => p.badge || p.originalPrice > p.price);
    dealsContainer.innerHTML = dealItems.map(p => {
      const discountPercent = Math.round(((p.originalPrice - p.price) / p.originalPrice) * 100);
      return `
        <div class="deal-card" onclick="window.openQuickView(${p.id})">
          <div class="deal-card-img-wrap">
            <img src="${p.image}" alt="${p.title}" class="deal-card-img" loading="lazy" />
          </div>
          <div class="deal-badge-row">
            <span class="deal-discount-badge">${discountPercent}% off</span>
            <span class="deal-badge-text">Limited time deal</span>
          </div>
          <div class="deal-price-row">
            <span class="deal-price">$${p.price.toFixed(2)}</span>
            <span class="deal-orig-price">$${p.originalPrice.toFixed(2)}</span>
          </div>
          <div class="deal-card-title">${p.title}</div>
        </div>
      `;
    }).join('');

    startDealsCountdown();
  }

  function startDealsCountdown() {
    const timerEl = document.getElementById('dealsCountdown');
    if (!timerEl) return;
    let totalSeconds = 9 * 3600 + 44 * 60 + 20; // 09:44:20

    setInterval(() => {
      if (totalSeconds > 0) totalSeconds--;
      const hours = String(Math.floor(totalSeconds / 3600)).padStart(2, '0');
      const mins = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, '0');
      const secs = String(totalSeconds % 60).padStart(2, '0');
      timerEl.textContent = `Ends in ${hours}:${mins}:${secs}`;
    }, 1000);
  }

  // --------------------------------------------------------
  // 4. RENDER STAR RATINGS HELPER
  // --------------------------------------------------------
  function renderStars(rating) {
    const fullStars = Math.floor(rating);
    const hasHalfStar = rating % 1 >= 0.5;
    let starsHtml = '';
    
    for (let i = 0; i < fullStars; i++) starsHtml += '★';
    if (hasHalfStar) starsHtml += '★';
    while (starsHtml.length < 5) starsHtml += '☆';
    
    return starsHtml;
  }

  // --------------------------------------------------------
  // 5. RENDER MAIN PRODUCTS GRID
  // --------------------------------------------------------
  function renderProducts() {
    if (!productsGrid) return;

    let filtered = productsData.filter(product => {
      const matchCat = (currentCategory === 'All') || (product.category.toLowerCase() === currentCategory.toLowerCase());
      const matchSearch = product.title.toLowerCase().includes(searchQuery.toLowerCase()) || 
                          product.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
                          product.category.toLowerCase().includes(searchQuery.toLowerCase());
      return matchCat && matchSearch;
    });

    if (productsCount) {
      productsCount.textContent = `(${filtered.length} item${filtered.length === 1 ? '' : 's'})`;
    }

    if (filtered.length === 0) {
      productsGrid.innerHTML = `
        <div style="grid-column: 1 / -1; text-align: center; padding: 60px 20px;">
          <h3 style="font-size: 20px; color: #333; margin-bottom: 8px;">No products found</h3>
          <p style="color: #666; font-size: 14px;">Try checking your spelling or use more general terms.</p>
          <button onclick="window.filterByCategory('All')" style="margin-top: 16px; background: #ffd814; padding: 8px 18px; border-radius: 20px; font-weight: 600;">View All Products</button>
        </div>
      `;
      return;
    }

    productsGrid.innerHTML = filtered.map(product => {
      const discount = Math.round(((product.originalPrice - product.price) / product.originalPrice) * 100);
      return `
        <div class="product-card" data-id="${product.id}">
          ${product.badge ? `<span class="product-ribbon ${product.badge === 'Deal of the Day' || product.badge === 'Limited time deal' ? 'deal' : product.badge === "Amazon's Choice" ? 'choice' : ''}">${product.badge}</span>` : ''}
          
          <div class="product-img-wrapper" onclick="window.openQuickView(${product.id})">
            <img src="${product.image}" alt="${product.title}" class="product-img" loading="lazy" />
          </div>

          <div class="product-info">
            <h3 class="product-title" onclick="window.openQuickView(${product.id})">${product.title}</h3>

            <div class="product-rating-row">
              <span class="stars">${renderStars(product.rating)}</span>
              <span class="rating-score">${product.rating}</span>
              <span class="review-count">(${product.reviewsCount.toLocaleString()})</span>
            </div>

            <div class="product-price-row">
              <div>
                <span class="price-symbol">$</span>
                <span class="price-main">${product.price.toFixed(2)}</span>
              </div>
              ${product.originalPrice > product.price ? `
                <span class="price-original">$${product.originalPrice.toFixed(2)}</span>
                <span class="price-discount">(${discount}% off)</span>
              ` : ''}
            </div>

            ${product.isPrime ? `
              <div class="prime-badge">
                <span class="prime-check">✓</span> prime
              </div>
            ` : ''}

            <div class="delivery-text">
              FREE delivery <span class="delivery-highlight">Tomorrow, 2 PM</span>
            </div>

            <div class="product-actions">
              <button class="btn-add-cart" onclick="window.addToCart(${product.id})">
                Add to Cart
              </button>
              <button class="btn-quick-view" onclick="window.openQuickView(${product.id})">
                Quick Look
              </button>
            </div>
          </div>
        </div>
      `;
    }).join('');
  }

  // --------------------------------------------------------
  // 6. FILTERING & SEARCH
  // --------------------------------------------------------
  window.filterByCategory = function(category) {
    currentCategory = category;
    
    // Update select dropdown if matching
    if (searchCategorySelect) {
      const matchOpt = Array.from(searchCategorySelect.options).find(o => o.value.toLowerCase() === category.toLowerCase());
      if (matchOpt) searchCategorySelect.value = matchOpt.value;
      else searchCategorySelect.value = 'All';
    }

    // Update filter pills
    filterPills.forEach(pill => {
      if (pill.getAttribute('data-category').toLowerCase() === category.toLowerCase()) {
        pill.classList.add('active');
      } else {
        pill.classList.remove('active');
      }
    });

    renderProducts();
    scrollToProducts();
  };

  filterPills.forEach(pill => {
    pill.addEventListener('click', () => {
      const cat = pill.getAttribute('data-category');
      window.filterByCategory(cat);
    });
  });

  function performSearch() {
    searchQuery = searchInput.value.trim();
    if (searchCategorySelect.value !== 'All') {
      currentCategory = searchCategorySelect.value;
    }
    renderProducts();
    scrollToProducts();
  }

  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      searchQuery = e.target.value;
      renderProducts();
    });

    searchInput.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') performSearch();
    });
  }

  if (searchBtn) {
    searchBtn.addEventListener('click', performSearch);
  }

  if (searchCategorySelect) {
    searchCategorySelect.addEventListener('change', (e) => {
      window.filterByCategory(e.target.value);
    });
  }

  function scrollToProducts() {
    const el = document.getElementById('productsSection');
    if (el) {
      const yOffset = -70;
      const y = el.getBoundingClientRect().top + window.pageYOffset + yOffset;
      window.scrollTo({ top: y, behavior: 'smooth' });
    }
  }

  // --------------------------------------------------------
  // 7. CART FUNCTIONALITY
  // --------------------------------------------------------
  function updateCartBadge() {
    const totalQty = cart.reduce((sum, item) => sum + item.quantity, 0);
    if (cartBadge) {
      cartBadge.textContent = totalQty;
    }
    localStorage.setItem('shopzone_cart', JSON.stringify(cart));
  }

  window.addToCart = function(productId, quantity = 1) {
    const product = productsData.find(p => p.id === productId);
    if (!product) return;

    const existingIndex = cart.findIndex(item => item.id === productId);
    if (existingIndex > -1) {
      cart[existingIndex].quantity += quantity;
    } else {
      cart.push({
        id: product.id,
        title: product.title,
        price: product.price,
        image: product.image,
        quantity: quantity
      });
    }

    updateCartBadge();
    showToast(`Added to Cart: "${product.title.slice(0, 30)}..."`);
    renderCartDrawer();
  };

  window.changeCartQty = function(productId, delta) {
    const itemIndex = cart.findIndex(item => item.id === productId);
    if (itemIndex > -1) {
      cart[itemIndex].quantity += delta;
      if (cart[itemIndex].quantity <= 0) {
        cart.splice(itemIndex, 1);
      }
      updateCartBadge();
      renderCartDrawer();
    }
  };

  window.removeFromCart = function(productId) {
    cart = cart.filter(item => item.id !== productId);
    updateCartBadge();
    renderCartDrawer();
    showToast('Item removed from cart');
  };

  function renderCartDrawer() {
    if (!cartItemsList) return;

    if (cart.length === 0) {
      cartItemsList.innerHTML = `
        <div class="empty-cart-msg">
          <div class="empty-cart-icon">🛒</div>
          <p style="font-weight: 600; font-size: 16px;">Your ShopZone Cart is empty</p>
          <span style="font-size: 13px;">Shop today's epic deals and discover trending items.</span>
        </div>
      `;
      if (cartSubtotal) cartSubtotal.textContent = '$0.00';
      return;
    }

    let subtotalVal = 0;
    cartItemsList.innerHTML = cart.map(item => {
      const itemTotal = item.price * item.quantity;
      subtotalVal += itemTotal;
      return `
        <div class="cart-item">
          <img src="${item.image}" alt="${item.title}" class="cart-item-img" />
          <div class="cart-item-details">
            <h4 class="cart-item-title">${item.title}</h4>
            <div class="cart-item-price">$${item.price.toFixed(2)}</div>
            <div class="cart-item-controls">
              <div class="qty-control">
                <button class="qty-btn" onclick="window.changeCartQty(${item.id}, -1)">−</button>
                <span class="qty-val">${item.quantity}</span>
                <button class="qty-btn" onclick="window.changeCartQty(${item.id}, 1)">+</button>
              </div>
              <span class="btn-remove-item" onclick="window.removeFromCart(${item.id})">Delete</span>
            </div>
          </div>
        </div>
      `;
    }).join('');

    if (cartSubtotal) {
      cartSubtotal.textContent = `$${subtotalVal.toFixed(2)}`;
    }
  }

  function openCartDrawer() {
    renderCartDrawer();
    if (cartDrawer) cartDrawer.classList.add('open');
    if (cartDrawerOverlay) cartDrawerOverlay.classList.add('open');
  }

  function closeCartDrawer() {
    if (cartDrawer) cartDrawer.classList.remove('open');
    if (cartDrawerOverlay) cartDrawerOverlay.classList.remove('open');
  }

  if (cartIconBtn) cartIconBtn.addEventListener('click', openCartDrawer);
  if (cartCloseBtn) cartCloseBtn.addEventListener('click', closeCartDrawer);
  if (cartDrawerOverlay) cartDrawerOverlay.addEventListener('click', closeCartDrawer);

  if (checkoutBtn) {
    checkoutBtn.addEventListener('click', () => {
      if (cart.length === 0) {
        showToast('Your cart is empty! Add items to continue.');
        return;
      }
      alert(`🎉 Thank you for checking out with ShopZone!\nTotal: ${cartSubtotal.textContent}\nDemo Order Placed Successfully.`);
      cart = [];
      updateCartBadge();
      renderCartDrawer();
      closeCartDrawer();
    });
  }

  // --------------------------------------------------------
  // 8. QUICK-VIEW MODAL
  // --------------------------------------------------------
  window.openQuickView = function(productId) {
    const product = productsData.find(p => p.id === productId);
    if (!product || !quickViewModal) return;

    const modalTitle = document.getElementById('modalTitle');
    const modalCategory = document.getElementById('modalCategory');
    const modalRatingStars = document.getElementById('modalRatingStars');
    const modalRatingCount = document.getElementById('modalRatingCount');
    const modalPrice = document.getElementById('modalPrice');
    const modalOrigPrice = document.getElementById('modalOrigPrice');
    const modalDesc = document.getElementById('modalDesc');
    const modalFeatures = document.getElementById('modalFeatures');
    const modalMainImg = document.getElementById('modalMainImg');
    const modalThumbs = document.getElementById('modalThumbs');
    const modalAddToCartBtn = document.getElementById('modalAddToCartBtn');
    const modalBuyNowBtn = document.getElementById('modalBuyNowBtn');

    modalTitle.textContent = product.title;
    modalCategory.textContent = product.category;
    modalRatingStars.textContent = renderStars(product.rating);
    modalRatingCount.textContent = `${product.rating} (${product.reviewsCount.toLocaleString()} ratings)`;
    modalPrice.textContent = `$${product.price.toFixed(2)}`;
    
    if (product.originalPrice > product.price) {
      modalOrigPrice.textContent = `Typical: $${product.originalPrice.toFixed(2)}`;
      modalOrigPrice.style.display = 'inline';
    } else {
      modalOrigPrice.style.display = 'none';
    }

    modalDesc.textContent = product.description;
    modalFeatures.innerHTML = product.features.map(f => `<li>${f}</li>`).join('');
    modalMainImg.src = product.image;

    // Thumbnails
    modalThumbs.innerHTML = product.images.map((imgUrl, i) => `
      <img src="${imgUrl}" class="modal-thumb ${i === 0 ? 'active' : ''}" onclick="window.switchModalImage('${imgUrl}', this)" alt="thumbnail" />
    `).join('');

    modalAddToCartBtn.onclick = () => {
      window.addToCart(product.id);
      quickViewModal.classList.remove('open');
    };

    modalBuyNowBtn.onclick = () => {
      window.addToCart(product.id);
      quickViewModal.classList.remove('open');
      openCartDrawer();
    };

    quickViewModal.classList.add('open');
  };

  window.switchModalImage = function(imgUrl, thumbEl) {
    const mainImg = document.getElementById('modalMainImg');
    if (mainImg) mainImg.src = imgUrl;
    document.querySelectorAll('.modal-thumb').forEach(t => t.classList.remove('active'));
    if (thumbEl) thumbEl.classList.add('active');
  };

  if (modalCloseBtn) {
    modalCloseBtn.addEventListener('click', () => {
      quickViewModal.classList.remove('open');
    });
  }

  if (quickViewModal) {
    quickViewModal.addEventListener('click', (e) => {
      if (e.target === quickViewModal) {
        quickViewModal.classList.remove('open');
      }
    });
  }

  // --------------------------------------------------------
  // 9. SIDEBAR DRAWER ("All" Hamburger Menu)
  // --------------------------------------------------------
  function openSidebar() {
    if (sidebarDrawer) sidebarDrawer.classList.add('open');
    if (sidebarOverlay) sidebarOverlay.classList.add('open');
  }

  function closeSidebar() {
    if (sidebarDrawer) sidebarDrawer.classList.remove('open');
    if (sidebarOverlay) sidebarOverlay.classList.remove('open');
  }

  if (sidebarOpenBtn) sidebarOpenBtn.addEventListener('click', openSidebar);
  if (sidebarCloseBtn) sidebarCloseBtn.addEventListener('click', closeSidebar);
  if (sidebarOverlay) sidebarOverlay.addEventListener('click', closeSidebar);

  document.querySelectorAll('.sidebar-item').forEach(item => {
    item.addEventListener('click', () => {
      const cat = item.getAttribute('data-cat');
      if (cat) {
        window.filterByCategory(cat);
        closeSidebar();
      }
    });
  });

  // --------------------------------------------------------
  // 10. LOCATION SELECTOR MODAL
  // --------------------------------------------------------
  if (locationBtn && locationModal) {
    locationBtn.addEventListener('click', () => {
      locationModal.classList.add('open');
    });
  }

  if (locationModalClose && locationModal) {
    locationModalClose.addEventListener('click', () => {
      locationModal.classList.remove('open');
    });
  }

  if (locationModal) {
    locationModal.addEventListener('click', (e) => {
      if (e.target === locationModal) locationModal.classList.remove('open');
    });
  }

  if (locApplyBtn && locZipInput) {
    locApplyBtn.addEventListener('click', () => {
      const zip = locZipInput.value.trim();
      if (zip && locDisplay) {
        locDisplay.textContent = `New York ${zip}`;
        showToast(`Delivery location updated to: ${zip}`);
        locationModal.classList.remove('open');
      }
    });
  }

  // --------------------------------------------------------
  // 11. TOAST NOTIFICATION UTILITY
  // --------------------------------------------------------
  function showToast(message) {
    let container = document.getElementById('toastContainer');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toastContainer';
      container.className = 'toast-container';
      document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.innerHTML = `
      <span class="toast-icon">✓</span>
      <span>${message}</span>
    `;
    container.appendChild(toast);

    setTimeout(() => toast.classList.add('show'), 10);
    setTimeout(() => {
      toast.classList.remove('show');
      setTimeout(() => toast.remove(), 300);
    }, 3200);
  }

  // --------------------------------------------------------
  // 12. BACK TO TOP
  // --------------------------------------------------------
  const backToTopBtn = document.getElementById('backToTopBtn');
  if (backToTopBtn) {
    backToTopBtn.addEventListener('click', () => {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

  // --------------------------------------------------------
  // RUN INITIAL RENDERS
  // --------------------------------------------------------
  initHeroSlider();
  renderPromoCards();
  renderDeals();
  renderProducts();
  updateCartBadge();

    // Open a product's quick view from a link such as index.html#product-2
  function openFromHash() {
    const m = location.hash.match(/^#product-(\d+)$/);
    if (m) window.openQuickView(parseInt(m[1], 10));
  }
  openFromHash();
  window.addEventListener('hashchange', openFromHash);
});
