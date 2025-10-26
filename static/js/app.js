// Global state
let products = [];
let cart = [];
let currentFilter = 'all';

// DOM elements
const productsGrid = document.getElementById('productsGrid');
const cartBtn = document.getElementById('cartBtn');
const cartSidebar = document.getElementById('cartSidebar');
const closeCart = document.getElementById('closeCart');
const cartCount = document.getElementById('cartCount');
const cartItems = document.getElementById('cartItems');
const cartTotal = document.getElementById('cartTotal');
const filterBtns = document.querySelectorAll('.filter-btn');
const overlay = document.createElement('div');
overlay.className = 'overlay';
document.body.appendChild(overlay);

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
    loadProducts();
    loadCart();
    setupEventListeners();
});

// Setup event listeners
function setupEventListeners() {
    cartBtn.addEventListener('click', openCart);
    closeCart.addEventListener('click', closeCartSidebar);
    overlay.addEventListener('click', closeCartSidebar);

    filterBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const category = btn.dataset.category;
            setActiveFilter(category);
            filterProducts(category);
        });
    });
}

// Load products from API
async function loadProducts() {
    try {
        showLoading();
        const response = await fetch('/api/products');
        products = await response.json();
        renderProducts(products);
    } catch (error) {
        console.error('Error loading products:', error);
        showError('Failed to load products');
    }
}

// Load cart from API
async function loadCart() {
    try {
        const response = await fetch('/api/cart');
        cart = await response.json();
        updateCartUI();
    } catch (error) {
        console.error('Error loading cart:', error);
    }
}

// Render products
function renderProducts(productsToRender) {
    if (!productsToRender || productsToRender.length === 0) {
        productsGrid.innerHTML = '<div class="loading">No products found</div>';
        return;
    }

    productsGrid.innerHTML = productsToRender.map(product => `
        <div class="product-card" data-product-id="${product.id}">
            <div class="product-image">
                <img src="${product.image_url}" alt="${product.name}" onerror="this.style.display='none'; this.parentElement.innerHTML='Product Image';">
            </div>
            <div class="product-info">
                <h3 class="product-name">${product.name}</h3>
                <p class="product-description">${product.description}</p>
                <div class="product-price">$${product.price.toFixed(2)}</div>
                ${product.sizes && product.sizes.length > 1 ? `
                    <div class="size-selector">
                        <label>Size:</label>
                        <div class="size-options">
                            ${product.sizes.map(size => `
                                <button class="size-option" data-size="${size}" onclick="selectSize(this, ${product.id})">
                                    ${size}
                                </button>
                            `).join('')}
                        </div>
                    </div>
                ` : ''}
                <button class="add-to-cart-btn" onclick="addToCart(${product.id})" ${!product.in_stock ? 'disabled' : ''}>
                    ${product.in_stock ? 'Add to Cart' : 'Out of Stock'}
                </button>
            </div>
        </div>
    `).join('');
}

// Select size
function selectSize(element, productId) {
    const productCard = document.querySelector(`[data-product-id="${productId}"]`);
    const sizeOptions = productCard.querySelectorAll('.size-option');
    sizeOptions.forEach(option => option.classList.remove('selected'));
    element.classList.add('selected');
}

// Add to cart
async function addToCart(productId) {
    const product = products.find(p => p.id === productId);
    if (!product || !product.in_stock) return;

    let selectedSize = 'One Size';
    if (product.sizes && product.sizes.length > 1) {
        const productCard = document.querySelector(`[data-product-id="${productId}"]`);
        const selectedSizeElement = productCard.querySelector('.size-option.selected');
        if (!selectedSizeElement) {
            alert('Please select a size');
            return;
        }
        selectedSize = selectedSizeElement.dataset.size;
    }

    try {
        const response = await fetch('/api/cart', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                product_id: productId,
                size: selectedSize,
                quantity: 1
            })
        });

        if (response.ok) {
            await loadCart(); // Reload cart from server
            showNotification('Item added to cart!');

            // Reset size selection
            const productCard = document.querySelector(`[data-product-id="${productId}"]`);
            const sizeOptions = productCard.querySelectorAll('.size-option');
            sizeOptions.forEach(option => option.classList.remove('selected'));
        } else {
            throw new Error('Failed to add to cart');
        }
    } catch (error) {
        console.error('Error adding to cart:', error);
        showNotification('Failed to add item to cart', 'error');
    }
}

// Update cart UI
function updateCartUI() {
    cartCount.textContent = cart.length;

    if (cart.length === 0) {
        cartItems.innerHTML = '<div class="empty-cart">Your cart is empty</div>';
        cartTotal.textContent = '0.00';
        return;
    }

    cartItems.innerHTML = cart.map((item, index) => `
        <div class="cart-item">
            <div class="cart-item-image">
                <img src="${item.product.image_url}" alt="${item.product.name}" onerror="this.style.display='none'; this.parentElement.innerHTML='Product';">
            </div>
            <div class="cart-item-details">
                <div class="cart-item-name">${item.product.name}</div>
                <div class="cart-item-size">Size: ${item.size}</div>
                <div class="cart-item-price">$${(item.product.price * item.quantity).toFixed(2)}</div>
                <div class="cart-item-quantity">
                    <button class="quantity-btn" onclick="updateQuantity(${index}, -1)">-</button>
                    <span class="quantity-display">${item.quantity}</span>
                    <button class="quantity-btn" onclick="updateQuantity(${index}, 1)">+</button>
                </div>
                <button class="remove-item" onclick="removeFromCart(${index})">Remove</button>
            </div>
        </div>
    `).join('');

    const total = cart.reduce((sum, item) => sum + (item.product.price * item.quantity), 0);
    cartTotal.textContent = total.toFixed(2);
}

// Update quantity
async function updateQuantity(index, change) {
    const item = cart[index];
    const newQuantity = item.quantity + change;

    if (newQuantity <= 0) {
        removeFromCart(index);
        return;
    }

    try {
        // Remove current item
        await fetch(`/api/cart/${index}`, { method: 'DELETE' });

        // Add item with new quantity
        await fetch('/api/cart', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                product_id: item.product_id,
                size: item.size,
                quantity: newQuantity
            })
        });

        await loadCart(); // Reload cart from server
    } catch (error) {
        console.error('Error updating quantity:', error);
        showNotification('Failed to update quantity', 'error');
    }
}

// Remove from cart
async function removeFromCart(index) {
    try {
        const response = await fetch(`/api/cart/${index}`, { method: 'DELETE' });
        if (response.ok) {
            await loadCart(); // Reload cart from server
        } else {
            throw new Error('Failed to remove item');
        }
    } catch (error) {
        console.error('Error removing from cart:', error);
        showNotification('Failed to remove item', 'error');
    }
}

// Filter products
function filterProducts(category) {
    const filtered = category === 'all'
        ? products
        : products.filter(p => p.category === category);
    renderProducts(filtered);
}

// Set active filter
function setActiveFilter(category) {
    currentFilter = category;
    filterBtns.forEach(btn => {
        btn.classList.toggle('active', btn.dataset.category === category);
    });
}

// Cart controls
function openCart() {
    cartSidebar.classList.add('open');
    overlay.classList.add('active');
    document.body.style.overflow = 'hidden';
}

function closeCartSidebar() {
    cartSidebar.classList.remove('open');
    overlay.classList.remove('active');
    document.body.style.overflow = '';
}

// Utility functions
function showLoading() {
    productsGrid.innerHTML = '<div class="loading">Loading products...</div>';
}

function showError(message) {
    productsGrid.innerHTML = `<div class="loading" style="color: #e74c3c;">${message}</div>`;
}

function showNotification(message, type = 'success') {
    const notification = document.createElement('div');
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: ${type === 'success' ? '#27ae60' : '#e74c3c'};
        color: white;
        padding: 16px 24px;
        border-radius: 8px;
        z-index: 10000;
        font-weight: 500;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        animation: slideIn 0.3s ease;
    `;
    notification.textContent = message;
    document.body.appendChild(notification);

    // Add animation
    const style = document.createElement('style');
    style.textContent = `
        @keyframes slideIn {
            from { transform: translateX(100%); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }
    `;
    document.head.appendChild(style);

    setTimeout(() => {
        notification.style.animation = 'slideIn 0.3s ease reverse';
        setTimeout(() => {
            document.body.removeChild(notification);
            document.head.removeChild(style);
        }, 300);
    }, 3000);
}

// Handle navigation
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        e.preventDefault();
        const target = this.getAttribute('href').substring(1);
        if (target === 'apparel') {
            setActiveFilter('apparel');
            filterProducts('apparel');
        } else if (target === 'accessories') {
            setActiveFilter('accessories');
            filterProducts('accessories');
        }

        // Scroll to products section
        document.querySelector('.products').scrollIntoView({
            behavior: 'smooth'
        });
    });
});

// Handle checkout
document.querySelector('.checkout-btn').addEventListener('click', () => {
    if (cart.length === 0) {
        showNotification('Your cart is empty', 'error');
        return;
    }

    const total = cart.reduce((sum, item) => sum + (item.product.price * item.quantity), 0);
    const itemCount = cart.reduce((sum, item) => sum + item.quantity, 0);

    showNotification(`Checkout: ${itemCount} items for $${total.toFixed(2)} - Integration with payment processor needed!`);
});